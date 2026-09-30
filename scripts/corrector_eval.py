# -*- coding: utf-8 -*-
"""4B 精检召回评测：错句改正率 / 正确句误改率 / 并发吞吐。

数据管线复用 threshold_sweep（fixtures 正确句＋合成池＋混淆词注入）。
错句逐句调 4B 分类为：正确改正 / 漏改 / 错改（含校验失败）；
正确句过 4B 统计误改；并发组测 vLLM 吞吐。

用法（服务器）：
    .venv/bin/python scripts/corrector_eval.py \
        --corrector-url http://127.0.0.1:8000/v1 \
        --corrector-model twnlp/ChineseErrorCorrector4-4B
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from threshold_sweep import collect_sentences, inject_typos, synthetic_sentences
from document_checker.typo.confusion import WRONG2RIGHT
from document_checker.typo.service_corrector import OpenAICorrector


def build_data(fixtures_dir: str):
    correct = collect_sentences(fixtures_dir)
    correct = correct + synthetic_sentences()
    wrong_items = inject_typos(correct)
    return correct, wrong_items


def classify_wrong(item: dict, corrections: list[dict] | None, error: str | None) -> dict:
    """错句结果分类：correct / missed / mischanged / invalid。"""
    wrong_word = item["kind"].split(":", 1)[1]
    right_word = WRONG2RIGHT.get(wrong_word, "")
    if error is not None:
        return {"label": "invalid", "detail": error}
    if not corrections:
        return {"label": "missed", "detail": "原样返回"}
    start, end = item["offset"], item["offset"] + len(wrong_word)
    for c in corrections:
        off = c.get("offset")
        if off is not None and start <= off < end and c.get("改为") and c["改为"] in right_word:
            return {"label": "correct", "detail": f"{c['原文']}→{c['改为']}"}
    return {"label": "mischanged",
            "detail": "; ".join(f"{c.get('原文')}→{c.get('改为')}@{c.get('offset')}" for c in corrections)}


def call_one(corrector: OpenAICorrector, sentence: str):
    """返回 (corrections|None, error|None, latency)。"""
    t0 = time.perf_counter()
    try:
        fixes = corrector.correct(sentence)
        return fixes, None, time.perf_counter() - t0
    except Exception as exc:  # 校验失败、HTTP 错误都记录为 error
        return None, str(exc)[:200], time.perf_counter() - t0


def eval_wrong(corrector: OpenAICorrector, wrong_items: list[dict], workers: int = 1):
    results = [None] * len(wrong_items)
    latencies = []
    def task(i):
        fixes, err, lat = call_one(corrector, wrong_items[i]["text"])
        latencies.append(lat)
        results[i] = classify_wrong(wrong_items[i], fixes, err)
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(task, range(len(wrong_items))))
    else:
        for i in range(len(wrong_items)):
            task(i)
    return results, latencies


def eval_correct(corrector: OpenAICorrector, sentences: list[str]):
    miscorrections = []
    latencies = []
    for t in sentences:
        fixes, err, lat = call_one(corrector, t)
        latencies.append(lat)
        if err is not None:
            miscorrections.append({"sentence": t, "type": "invalid", "detail": err})
        elif fixes:
            miscorrections.append({"sentence": t, "type": "mischanged",
                                   "detail": "; ".join(f"{c.get('原文')}→{c.get('改为')}" for c in fixes)})
    return miscorrections, latencies


def summarize(results, wrong_items):
    per_pair = defaultdict(lambda: defaultdict(int))
    totals = defaultdict(int)
    for r, item in zip(results, wrong_items):
        pair = item["kind"].split(":", 1)[1] + "→" + WRONG2RIGHT.get(item["kind"].split(":", 1)[1], "?")
        per_pair[pair][r["label"]] += 1
        totals[r["label"]] += 1
    return per_pair, totals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="tests/fixtures/manual")
    ap.add_argument("--corrector-url", default=os.environ.get(
        "DOCUMENT_CHECKER_CORRECTOR_BASE_URL", "http://127.0.0.1:8000/v1"))
    ap.add_argument("--corrector-model", default=os.environ.get(
        "DOCUMENT_CHECKER_CORRECTOR_MODEL", "twnlp/ChineseErrorCorrector4-4B"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="调试时限制每类样本数")
    ap.add_argument("--dry-run", action="store_true", help="只建数据不发请求")
    ap.add_argument("--out", default="data/corrector_eval.json")
    args = ap.parse_args()

    correct, wrong_items = build_data(args.fixtures)
    if args.limit:
        correct, wrong_items = correct[:args.limit], wrong_items[:args.limit]
    print(f"正确句 {len(correct)} 条，注入错句 {len(wrong_items)} 条", flush=True)
    if args.dry_run:
        kinds = defaultdict(int)
        for w in wrong_items:
            kinds[w["kind"]] += 1
        print("注入分布:", dict(kinds))
        return

    corrector = OpenAICorrector(model=args.corrector_model, base_url=args.corrector_url,
                                protocol="corrected_text")

    t0 = time.perf_counter()
    wrong_results, wrong_lat = eval_wrong(corrector, wrong_items, workers=1)
    serial_s = time.perf_counter() - t0
    print(f"错句串行评测 {len(wrong_items)} 句：{serial_s:.1f}s", flush=True)

    t0 = time.perf_counter()
    miscorrections, correct_lat = eval_correct(corrector, correct)
    correct_s = time.perf_counter() - t0
    print(f"正确句误改评测 {len(correct)} 句：{correct_s:.1f}s，误改 {len(miscorrections)} 句", flush=True)

    t0 = time.perf_counter()
    conc_results, conc_lat = eval_wrong(corrector, wrong_items, workers=args.workers)
    conc_s = time.perf_counter() - t0
    print(f"错句并发评测（{args.workers} 路）：{conc_s:.1f}s", flush=True)

    per_pair, totals = summarize(wrong_results, wrong_items)
    n = len(wrong_items)
    lat_all = sorted(wrong_lat + correct_lat)
    p95 = lat_all[int(len(lat_all) * 0.95)] if lat_all else 0
    report = {
        "model": args.corrector_model, "url": args.corrector_url,
        "wrong_total": n, "correct_total": len(correct),
        "wrong_results": {"totals": dict(totals),
                          "rates": {k: round(v / n, 4) for k, v in totals.items()},
                          "per_pair": {p: dict(c) for p, c in sorted(per_pair.items())},
                          "detail": [{"item": i, "result": r} for i, r in zip(wrong_items, wrong_results)]},
        "correct_miscorrection": {"count": len(miscorrections),
                                  "rate": round(len(miscorrections) / len(correct), 4),
                                  "cases": miscorrections[:20]},
        "timing": {"serial_wrong_seconds": round(serial_s, 1),
                   "correct_seconds": round(correct_s, 1),
                   "concurrent_wrong_seconds": round(conc_s, 1),
                   "workers": args.workers,
                   "mean_latency": round(sum(lat_all) / len(lat_all), 3) if lat_all else 0,
                   "p95_latency": round(p95, 3),
                   "serial_qps": round(n / serial_s, 2) if serial_s else 0,
                   "concurrent_qps": round(n / conc_s, 2) if conc_s else 0},
        "concurrent_consistency": sum(
            1 for a, b in zip(wrong_results, conc_results) if a["label"] == b["label"]),
        "caveat": "注入错句分布不等于真实错字分布；合成集上的相对表现，非最终精度验收。",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n混淆词 | 样本 | 正确改正 | 漏改 | 错改 | 校验失败")
    for p, c in sorted(per_pair.items()):
        total = sum(c.values())
        print(f"{p} | {total} | {c.get('correct', 0)} | {c.get('missed', 0)} | "
              f"{c.get('mischanged', 0)} | {c.get('invalid', 0)}")
    print(f"\n合计改正率 {totals.get('correct', 0) / n:.1%}，误改率 {report['correct_miscorrection']['rate']:.1%}")
    print(f"串行 {report['timing']['serial_qps']} QPS / 并发 {report['timing']['concurrent_qps']} QPS，"
          f"结果已写入 {out}")


if __name__ == "__main__":
    main()
