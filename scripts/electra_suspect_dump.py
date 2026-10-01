# -*- coding: utf-8 -*-
"""诊断：ELECTRA 嫌疑标记与已知 Finding 位置的对照。

用于验证「检测器—精检交叉验证」假设：模型幻觉建议的 offset 是否都不在
ELECTRA 嫌疑范围内，而真错字的 offset 是否在范围内。

用法（服务器）：
    export CED_MODEL_DIR=$HOME/doc-format-checker/data/models/ChineseErrorDetectorElectra
    .venv/bin/python scripts/electra_suspect_dump.py <docx路径> [threshold]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from document_checker.docx_parser import parse_document
from document_checker.typo.splitter import split_paragraph
from document_checker.typo.filters import should_skip
from document_checker.typo.detector import ElectraDetector

# (段号[1-based], 字序号[1-based], 原文, 是否真错字, 说明)
KNOWN = [
    (1, 6, "资全", True, "兜底真：资金"),
    (1, 8, "官理", True, "兜底真：管理"),
    (4, 29, "按排", True, "兜底真：安排"),
    (6, 66, "布署", True, "兜底真：部署"),
    (15, 91, "他", False, "幻觉：其他"),
    (25, 116, "官", True, "模型真：监官局→监管局"),
    (27, 127, "应", False, "幻觉：应将"),
    (32, 67, "定", False, "幻觉：制定"),
    (32, 97, "事", False, "幻觉：事中"),
    (37, 34, "及", False, "幻觉：及时"),
    (37, 53, "退", False, "幻觉：退出"),
    (39, 99, "相", False, "幻觉：相应"),
    (39, 101, "", False, "幻觉：加字负"),
    (41, 58, "报", False, "幻觉：报→鲍"),
]


def main():
    path, threshold = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 0.85
    model = parse_document(path)
    sentences = []
    for p in model.paragraphs:
        if p.is_blank:
            continue
        for s in split_paragraph(p.index, p.text):
            if not should_skip(s.text):
                sentences.append(s)
    print(f"检查句数 {len(sentences)}")
    detector = ElectraDetector(threshold=threshold, device="auto")
    results = detector.detect([s.text for s in sentences])

    flagged = {}
    for s, res in zip(sentences, results):
        if res is not None:
            flagged[(s.para_index, s.start)] = (s, res)
    print(f"ELECTRA 标记 {len(flagged)} 句：")
    for (pi, st), (s, res) in sorted(flagged.items()):
        print(f"  第{pi + 1}段·句首{s.start + 1} 嫌疑字={res.suspect_chars} | {s.text[:38]}")

    print("\nFinding 对照：")
    rows = []
    for para, pos, src, is_true, note in KNOWN:
        idx = pos - 1
        hit = None
        for (pi, st), (s, res) in flagged.items():
            if pi == para - 1 and st <= idx < st + len(s.text):
                rel = idx - st
                n = max(len(src), 1)
                covered = any(rel <= c < rel + n or c <= rel < c + len(ch)
                              for c, ch, _ in res.suspect_chars)
                hit = covered
                break
        rows.append({"para": para, "pos": pos, "src": src, "true_typo": is_true,
                     "note": note, "electra_covered": hit})
        mark = {True: "真", False: "假"}[is_true]
        cov = {True: "✓在嫌疑范围", False: "✗不在", None: "○句子未被标记"}[hit]
        print(f"  第{para}段·第{pos}字 [{mark}] {src or '(增字)'} | {cov} | {note}")

    tp = sum(1 for r in rows if r["true_typo"] and r["electra_covered"])
    fp_filtered = sum(1 for r in rows if not r["true_typo"] and not r["electra_covered"])
    print(f"\n交叉验证假设：真错字被覆盖 {tp}/5，幻觉被滤除 {fp_filtered}/9")
    Path("data/electra_suspect_dump.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
