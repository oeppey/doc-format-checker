# -*- coding: utf-8 -*-
"""T-02：ELECTRA 初筛阈值标定扫描。

做法：从人工 fixtures 提取正确句；把混淆词表（含拆出的单字对）注入生成
带位置标注的错句。一次推理（threshold=0）收集全部字符分数，再离线扫阈值，
输出各阈值下的召回、误报、进入精检比例；并测量两种批量大小下的吞吐。

用法（服务器）：
    export CED_MODEL_DIR=~/doc-format-checker/data/models/ChineseErrorDetectorElectra
    .venv/bin/python scripts/threshold_sweep.py --device cuda

注意：注入错句的分布不等于真实错字分布，结果用于定阈值区间，不是精度验收。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from document_checker.docx_parser import parse_document
from document_checker.typo.confusion import CONFUSION_PAIRS
from document_checker.typo.detector import ElectraDetector
from document_checker.typo.splitter import split_paragraph

THRESHOLDS = [round(0.50 + 0.05 * i, 2) for i in range(10)]  # 0.50 … 0.95

# ---- 公文句式合成池：fixtures 文本同源性太高，去重后只有十几句，不足以标定。
# 用「主语 × 动作 × 事项」槽位合成多样化正确句；动作词特意覆盖混淆词表中的
# 正确写法（部署/安排/贯彻/管理/资金/期间/账户/即使/补贴/曝光），保证注入可达。
_SUBJECTS = ["市纪委监委", "办公室", "各科室", "专案组", "审查调查室", "工作组",
             "各县区局", "财务科", "信息中心", "督查组"]
_ACTIONS = ["部署", "安排", "组织", "开展", "推进", "落实", "检查", "督导",
            "贯彻", "执行", "管理", "调度"]
_OBJECTS = ["专项检查", "材料归档", "线索处置", "廉政教育", "资金管理", "问题整改",
            "回头看工作", "账户核对", "补贴发放", "信息公开", "期间费用审计", "数据汇总"]
_TEMPLATES = [
    "请{s}于本周五前{a}{o}，并将进展情况报办公室。",
    "{s}负责{a}{o}，工作中要注意保密纪律。",
    "经研究，决定由{s}牵头{a}{o}。",
    "{s}要按照有关要求{a}{o}，确保任务按时完成。",
    "请{s}高度重视，认真{a}{o}，不得敷衍塞责。",
    "{s}已{a}{o}，目前进展顺利。",
    "各有关单位要配合{s}做好{o}，形成工作合力。",
    "即使在任务繁重的情况下，{s}也要按时{a}{o}。",
    "对检查中曝光的问题，{s}要逐一{a}整改。",
]
_SYNTH_SIZE = 240


def synthetic_sentences(size: int = _SYNTH_SIZE) -> list[str]:
    """确定性合成公文句式，补足 fixtures 同源文本的多样性不足。"""
    import itertools
    import random
    pool = []
    combos = list(itertools.product(_SUBJECTS, _ACTIONS, _OBJECTS))
    random.Random(42).shuffle(combos)
    templates = _TEMPLATES * ((size // len(_TEMPLATES)) + 2)
    for i, (s, a, o) in enumerate(combos):
        if len(pool) >= size:
            break
        sent = templates[i % len(templates)].format(s=s, a=a, o=o)
        if sent not in pool:
            pool.append(sent)
    return pool

# 从混淆词表拆出单字替换对（正确字 → 错字），词级注入覆盖不到的句子用字级补充
CHAR_WRONG_OF = {}
for _wrong, _right, _ in CONFUSION_PAIRS:
    if len(_wrong) == len(_right):
        for w, r in zip(_wrong, _right):
            if w != r:
                CHAR_WRONG_OF.setdefault(r, w)


def collect_sentences(fixtures_dir: str) -> list[str]:
    """从 fixtures 全部 DOCX 提取去重后的中文句子。"""
    seen, out = set(), []
    for path in sorted(Path(fixtures_dir).rglob("*.docx")):
        model = parse_document(str(path))
        for p in model.paragraphs:
            for sent in split_paragraph(p.index, p.text):
                t = sent.text.strip()
                if 8 <= len(t) <= 120 and any("一" <= c <= "鿿" for c in t):
                    if t not in seen:
                        seen.add(t)
                        out.append(t)
    return out


def inject_typos(sentences: list[str]) -> list[dict]:
    """优先词级注入（混淆词表），否则字级注入。返回错句及注入位置。"""
    wrong = []
    for t in sentences:
        done = False
        for w, r, _ in CONFUSION_PAIRS:
            if r in t:
                i = t.index(r)
                wrong.append({"text": t[:i] + w + t[i + len(r):], "source": t,
                              "offset": i, "kind": f"word:{w}"})
                done = True
                break
        if done:
            continue
        for i, c in enumerate(t):
            w = CHAR_WRONG_OF.get(c)
            if w:
                wrong.append({"text": t[:i] + w + t[i + 1:], "source": t,
                              "offset": i, "kind": f"char:{c}->{w}"})
                break
    return wrong


def run_pass(detector, sentences: list[str], batch_size: int):
    """一次推理，返回每句 [(char_start, char, score), ...] 与耗时。"""
    detector.batch_size = batch_size
    start = time.perf_counter()
    results = detector.detect(sentences)
    elapsed = time.perf_counter() - start
    hits_per_sentence = [
        [(off, ch, score) for off, ch, score in (r.suspect_chars if r else [])]
        for r in results
    ]
    return hits_per_sentence, elapsed, len(detector.last_truncated)


def sweep(correct_hits, wrong_hits, wrong_items):
    """离线扫阈值。wrong 句的注入位置落在任一超阈值字符区间即算字级命中。"""
    rows = []
    n_correct, n_wrong = len(correct_hits), len(wrong_hits)
    for t in THRESHOLDS:
        flagged_correct = sum(1 for hits in correct_hits if any(s >= t for _, _, s in hits))
        flagged_wrong = 0
        char_hit = 0
        for hits, item in zip(wrong_hits, wrong_items):
            over = [(off, ch) for off, ch, s in hits if s >= t]
            if not over:
                continue
            flagged_wrong += 1
            if any(off == item["offset"] or (off <= item["offset"] < off + len(ch))
                   for off, ch in over):
                char_hit += 1
        rows.append({
            "threshold": t,
            "wrong_sentence_recall": round(flagged_wrong / n_wrong, 4) if n_wrong else None,
            "char_level_hit": round(char_hit / n_wrong, 4) if n_wrong else None,
            "correct_false_positive": round(flagged_correct / n_correct, 4) if n_correct else None,
            "gate_pass_ratio": round((flagged_correct + flagged_wrong) / (n_correct + n_wrong), 4),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="tests/fixtures/manual")
    ap.add_argument("--model-dir", default=os.environ.get(
        "CED_MODEL_DIR", "data/models/ChineseErrorDetectorElectra"))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--batch-sizes", default="8,32")
    ap.add_argument("--out", default="data/threshold_sweep.json")
    args = ap.parse_args()

    t0 = time.perf_counter()
    detector = ElectraDetector(args.model_dir, threshold=0.0, device=args.device)
    load_s = time.perf_counter() - t0

    correct = collect_sentences(args.fixtures)
    n_fixtures = len(correct)
    correct = correct + synthetic_sentences()
    print(f"fixtures 去重后 {n_fixtures} 句；合成池补足至 {len(correct)} 句", flush=True)
    wrong_items = inject_typos(correct)
    wrong_texts = [w["text"] for w in wrong_items]
    print(f"正确句 {len(correct)} 条，注入错句 {len(wrong_items)} 条", flush=True)

    # 批量 8 跑一次（正确＋错误），记录吞吐；批量 32 再跑一次对比
    all_hits, timing = {}, {}
    for bs in [int(x) for x in args.batch_sizes.split(",")]:
        key = f"bs{bs}"
        ch, t1, tr1 = run_pass(detector, correct, bs)
        wh, t2, tr2 = run_pass(detector, wrong_texts, bs)
        all_hits[key] = (ch, wh)
        timing[key] = {"correct_seconds": round(t1, 3), "wrong_seconds": round(t2, 3),
                       "sentences_per_second": round((len(correct) + len(wrong_texts)) / (t1 + t2), 1),
                       "truncated": tr1 + tr2}
        print(f"batch={bs}: 正确 {t1:.2f}s + 错误 {t2:.2f}s，"
              f"{timing[key]['sentences_per_second']} 句/秒", flush=True)

    # 指标以 batch=8 的结果为准（阈值在 detect 外部计算，与批量无关）
    first = f"bs{args.batch_sizes.split(',')[0]}"
    rows = sweep(all_hits[first][0], all_hits[first][1], wrong_items)

    report = {
        "model_dir": args.model_dir, "device": args.device,
        "load_seconds": round(load_s, 2),
        "correct_from_fixtures": n_fixtures, "correct_total": len(correct),
        "wrong_sentences": len(wrong_items),
        "injection_kinds": {k.split(":")[0]: sum(1 for w in wrong_items if w["kind"].startswith(k.split(":")[0]))
                            for k in {w["kind"] for w in wrong_items}},
        "timing": timing,
        "sweep": rows,
        "caveat": "注入错句分布不等于真实错字分布；结果用于定阈值区间，不是精度验收。",
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n阈值 | 错句召回 | 字级命中 | 正确句误报 | 进入精检比例")
    for r in rows:
        print(f"{r['threshold']:.2f} | {r['wrong_sentence_recall']} | "
              f"{r['char_level_hit']} | {r['correct_false_positive']} | {r['gate_pass_ratio']}")
    print(f"\n结果已写入 {out_path}")


if __name__ == "__main__":
    main()
