# -*- coding: utf-8 -*-
"""词表兜底确定性评测：本地运行，不需要模型服务。

1. 139 条注入错句：兜底按词对的直接命中率；
2. 结合 data/corrector_eval.json 基线（4B 无提示），计算「模型 ∪ 兜底」联合改正率；
3. 256 条正确句：兜底误报数（词表确定性的核心验收点，应为 0）。

用法：
    python scripts/fallback_eval.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corrector_eval import build_data
from document_checker.typo.confusion import FALLBACK_PAIRS, dict_fallback_fixes

FALLBACK_WORDS = {w for w, _, _ in FALLBACK_PAIRS}


def fallback_catches(item: dict) -> bool:
    """兜底是否命中注入错字（位置与词都对）。"""
    wrong_word = item["kind"].split(":", 1)[1]
    start, end = item["offset"], item["offset"] + len(wrong_word)
    return any(start <= f["offset"] < end and f["原文"] == wrong_word
               for f in dict_fallback_fixes(item["text"]))


def main():
    correct, wrong_items = build_data("tests/fixtures/manual")
    print(f"正确句 {len(correct)} 条，注入错句 {len(wrong_items)} 条")

    per_pair = defaultdict(lambda: [0, 0])  # 词 -> [兜底命中, 总数]
    for item in wrong_items:
        word = item["kind"].split(":", 1)[1]
        per_pair[word][1] += 1
        if fallback_catches(item):
            per_pair[word][0] += 1

    fp = [t for t in correct if dict_fallback_fixes(t)]

    baseline_path = Path("data/corrector_eval.json")
    joint = {}
    if baseline_path.is_file():
        base = json.loads(baseline_path.read_text(encoding="utf-8"))
        details = base["wrong_results"]["detail"]
        assert len(details) == len(wrong_items), "基线数据与当前样本数不一致"
        for d, item in zip(details, wrong_items):
            word = item["kind"].split(":", 1)[1]
            model_ok = d["result"]["label"] == "correct"
            fb_ok = fallback_catches(item)
            joint.setdefault(word, [0, 0, 0, 0])  # 模型对, 兜底中, 联合对, 总数
            joint[word][0] += model_ok
            joint[word][1] += fb_ok
            joint[word][2] += model_ok or fb_ok
            joint[word][3] += 1

    report = {
        "fallback_pairs": [f"{w}→{r}" for w, r, _ in FALLBACK_PAIRS],
        "per_pair": {w: {"fallback_hit": v[0], "total": v[1]} for w, v in sorted(per_pair.items())},
        "false_positives": {"count": len(fp), "sentences": fp[:10]},
        "joint_with_baseline": {w: {"model": v[0], "fallback": v[1],
                                    "joint": v[2], "total": v[3]}
                                for w, v in sorted(joint.items())},
    }
    out = Path("data/fallback_eval.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n混淆词 | 样本 | 4B 基线改正 | 兜底命中 | 联合改正")
    for w, v in sorted(joint.items()):
        print(f"{w} | {v[3]} | {v[0]} | {v[1]} | {v[2]}")
    if joint:
        total = sum(v[3] for v in joint.values())
        print(f"\n合计：4B 基线 {sum(v[0] for v in joint.values()) / total:.1%}，"
              f"联合 {sum(v[2] for v in joint.values()) / total:.1%}，"
              f"正确句误报 {len(fp)}/{len(correct)}")
    print(f"结果已写入 {out}")


if __name__ == "__main__":
    main()
