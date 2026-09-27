# -*- coding: utf-8 -*-
"""混淆集：错字注入（造测试数据）+ 启发式兜底检测共用一个 (错→对) 词表。"""
from __future__ import annotations

# (错误写法, 正确写法, 类型)——同音字 / 形近字 / 习惯性误用
CONFUSION_PAIRS = [
    ("布署", "部署", "同音"),
    ("补帖", "补贴", "同音"),
    ("帐户", "账户", "习惯性误用"),
    ("既使", "即使", "同音"),
    ("按排", "安排", "同音"),
    ("暴光", "曝光", "同音"),
    ("贯切", "贯彻", "形近"),
    ("监官", "监管", "形近"),
    ("资全", "资金", "形近"),
    ("官理", "管理", "形近"),
    ("其问", "期间", "形近"),
    ("在再", "在再", None),   # 占位防误用，实际见下文专项
]
CONFUSION_PAIRS = [p for p in CONFUSION_PAIRS if p[2]]

WRONG2RIGHT = {w: r for w, r, _ in CONFUSION_PAIRS}


def inject_typos_docx(src_path: str, out_path: str, pairs: list[str] | None = None):
    """在已生成的 docx 里注入错字：把正文 run 中出现的"正确写法"替换为"错误写法"。
    每对只注入第一次出现。返回注入明细 [(错误, 正确, 段落号)]。"""
    from docx import Document

    right2wrong = {r: w for w, r, _ in CONFUSION_PAIRS}
    want = pairs or list(right2wrong)   # 参数传"正确写法"，注入时替换成错误写法

    doc = Document(src_path)
    injected = []
    used = set()
    for pi, para in enumerate(doc.paragraphs):
        for run in para.runs:
            if not run.text:
                continue
            for right in want:
                wrong = right2wrong.get(right)
                if not wrong or right in used:
                    continue
                if right in run.text:
                    run.text = run.text.replace(right, wrong, 1)
                    injected.append((wrong, right, pi + 1))
                    used.add(right)
    doc.save(out_path)
    return injected
