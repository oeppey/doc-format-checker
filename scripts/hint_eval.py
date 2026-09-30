# -*- coding: utf-8 -*-
"""suspect_chars 提示对照实验：ELECTRA 嫌疑字提示能否压下 4B 漏改。

与 corrector_eval.py 使用同一数据管线和分类口径，差别在于：
1. 错句先过 ELECTRA，把 suspect_chars 作为提示传给 4B；
2. 同时记录 ELECTRA 对注入错字的字符级召回（提示覆盖率）；
3. 正确句同样先过 ELECTRA，仅被标记的句子带提示，测误改率变化。

用法（服务器）：
    export CED_MODEL_DIR=$HOME/doc-format-checker/data/models/ChineseErrorDetectorElectra
    .venv/bin/python scripts/hint_eval.py \
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corrector_eval import build_data, classify_wrong, summarize
from document_checker.typo.confusion import WRONG2RIGHT
from document_checker.typo.detector import ElectraDetector
from document_checker.typo.service_corrector import OpenAICorrector


def detect_all(detector: ElectraDetector, sentences: list[str]):
    """分批 detect，返回 list[SuspectResult|None]。"""
    results = []
    for start in range(0, len(sentences), detector.batch_size):
        results.extend(detector.detect(sentences[start:start + detector.batch_size]))
    return results


def electra_recall(wrong_items, detections):
    """ELECTRA 是否标记了句子、以及标记是否覆盖注入区间。"""
    flagged = covered = 0
    for item, det in zip(wrong_items, detections):
        if det is None:
            continue
        flagged += 1
        wrong_word = item["kind"].split(":", 1)[1]
        start, end = item["offset"], item["offset"] + len(wrong_word)
        if any(start <= pos < end for pos, _, _ in det.suspect_chars):
            covered += 1
    return flagged, covered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="tests/fixtures/manual")
    ap.add_argument("--corrector-url", default=os.environ.get(
        "DOCUMENT_CHECKER_CORRECTOR_BASE_URL", "http://127.0.0.1:8000/v1"))
    ap.add_argument("--corrector-model", default=os.environ.get(
        "DOCUMENT_CHECKER_CORRECTOR_MODEL", "twnlp/ChineseErrorCorrector4-4B"))
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="data/hint_eval.json")
    ap.add_argument("--baseline", default="data/corrector_eval.json",
                    help="无提示基线结果，用于对比")
    args = ap.parse_args()

    correct, wrong_items = build_data(args.fixtures)
    if args.limit:
        correct, wrong_items = correct[:args.limit], wrong_items[:args.limit]
    print(f"正确句 {len(correct)} 条，注入错句 {len(wrong_items)} 条", flush=True)
    if args.dry_run:
        return

    detector = ElectraDetector(threshold=args.threshold, device="auto")
    corrector = OpenAICorrector(model=args.corrector_model, base_url=args.corrector_url,
                                protocol="corrected_text")

    wrong_texts = [w["text"] for w in wrong_items]
    wrong_det = detect_all(detector, wrong_texts)
    flagged, covered = electra_recall(wrong_items, wrong_det)
    print(f"ELECTRA 标记 {flagged}/{len(wrong_items)} 句，"
          f"其中覆盖注入错字 {covered} 句", flush=True)

    t0 = time.perf_counter()
    wrong_results = []
    for item, det in zip(wrong_items, wrong_det):
        hints = det.suspect_chars if det else None
        try:
            fixes = corrector.correct(item["text"], hints)
            wrong_results.append(classify_wrong(item, fixes, None))
        except Exception as exc:
            wrong_results.append(classify_wrong(item, None, str(exc)[:200]))
    wrong_s = time.perf_counter() - t0
    print(f"错句带提示评测 {len(wrong_items)} 句：{wrong_s:.1f}s", flush=True)

    t0 = time.perf_counter()
    correct_det = detect_all(detector, correct)
    miscorrections = []
    hinted_correct = 0
    for text, det in zip(correct, correct_det):
        hints = det.suspect_chars if det else None
        if hints:
            hinted_correct += 1
        try:
            fixes = corrector.correct(text, hints)
            if fixes:
                miscorrections.append({"sentence": text, "type": "mischanged", "hinted": bool(hints),
                                       "detail": "; ".join(f"{c.get('原文')}→{c.get('改为')}" for c in fixes)})
        except Exception as exc:
            miscorrections.append({"sentence": text, "type": "invalid", "hinted": bool(hints),
                                   "detail": str(exc)[:200]})
    correct_s = time.perf_counter() - t0
    print(f"正确句评测 {len(correct)} 句（ELECTRA 标记 {hinted_correct} 句）："
          f"{correct_s:.1f}s，误改 {len(miscorrections)} 句", flush=True)

    per_pair, totals = summarize(wrong_results, wrong_items)
    n = len(wrong_items)
    report = {
        "model": args.corrector_model, "threshold": args.threshold,
        "electra": {"flagged": flagged, "covered_injection": covered, "total": n},
        "wrong_results": {"totals": dict(totals),
                          "rates": {k: round(v / n, 4) for k, v in totals.items()},
                          "per_pair": {p: dict(c) for p, c in sorted(per_pair.items())},
                          "detail": [{"item": i, "result": r} for i, r in zip(wrong_items, wrong_results)]},
        "correct_miscorrection": {"count": len(miscorrections),
                                  "rate": round(len(miscorrections) / len(correct), 4),
                                  "electra_flagged_correct": hinted_correct,
                                  "cases": miscorrections[:20]},
        "timing": {"wrong_seconds": round(wrong_s, 1), "correct_seconds": round(correct_s, 1)},
    }
    baseline_path = Path(args.baseline)
    if baseline_path.is_file():
        base = json.loads(baseline_path.read_text(encoding="utf-8"))
        report["baseline"] = {"wrong_rates": base["wrong_results"]["rates"],
                              "per_pair": base["wrong_results"]["per_pair"],
                              "miscorrection_rate": base["correct_miscorrection"]["rate"]}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    base_pair = report.get("baseline", {}).get("per_pair", {})
    print("\n混淆词 | 样本 | 基线改正 | 提示后改正 | 漏改变化")
    for p, c in sorted(per_pair.items()):
        base_correct = base_pair.get(p, {}).get("correct", "-")
        print(f"{p} | {sum(c.values())} | {base_correct} | {c.get('correct', 0)} | "
              f"{base_pair.get(p, {}).get('missed', '-')}→{c.get('missed', 0)}")
    print(f"\n合计改正率 {totals.get('correct', 0) / n:.1%}"
          f"（基线 {report.get('baseline', {}).get('wrong_rates', {}).get('correct', 0):.1%}），"
          f"误改率 {report['correct_miscorrection']['rate']:.1%}"
          f"（基线 {report.get('baseline', {}).get('miscorrection_rate', 0):.1%}）")
    print(f"结果已写入 {out}")


if __name__ == "__main__":
    main()
