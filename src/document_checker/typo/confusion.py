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

# 词表兜底：公文中可确定性判误的写法，不经过模型直接给替换建议。
# 收录标准：现代公文语境下没有合法用法、且不是更长专名的一部分。
# 监官（古代官名）、其问（引文/文言中可合法出现）暂不收录，待业务确认。
FALLBACK_PAIRS = [
    ("布署", "部署", "同音"),
    ("补帖", "补贴", "同音"),
    ("帐户", "账户", "习惯性误用"),
    ("既使", "即使", "同音"),
    ("按排", "安排", "同音"),
    ("暴光", "曝光", "同音"),
    ("贯切", "贯彻", "形近"),
    ("资全", "资金", "形近"),
    ("官理", "管理", "形近"),
]


# 语境守卫：错词若是「前词尾字＋后词首字」的跨界拼接则不报。
# pre：错词前一字在集合内时跳过（如「投资全部」含「资全」）；
# post：错词后一字在集合内时跳过（如「按排名」含「按排」）。
FALLBACK_EXCLUDE = {
    "资全": {"pre": "投合外集增引工"},   # 投资/合资/外资/集资/增资/引资/工资＋全…
    "官理": {"pre": "法警教长军"},       # 法官/警官/教官/长官/军官＋理…
    "按排": {"post": "名序位期班"},      # 按排名/排序/排位/排期/排班
    "贯切": {"pre": "一"},               # 一贯切实
    "布署": {"pre": "发"},               # 发布署名
}


def dict_fallback_fixes(sentence: str) -> list[dict]:
    """对单句做确定性词表检查，返回与精检器同构的 fixes（含 offset）。"""
    from .corrector import validate_corrections

    items = []
    for wrong, right, kind in FALLBACK_PAIRS:
        guard = FALLBACK_EXCLUDE.get(wrong, {})
        start = 0
        while (pos := sentence.find(wrong, start)) >= 0:
            start = pos + len(wrong)
            prev = sentence[pos - 1] if pos > 0 else ""
            nxt = sentence[pos + len(wrong)] if pos + len(wrong) < len(sentence) else ""
            if prev and prev in guard.get("pre", ""):
                continue
            if nxt and nxt in guard.get("post", ""):
                continue
            items.append({"原文": wrong, "改为": right,
                          "理由": f"词表兜底：{kind}字误写", "offset": pos})
    return validate_corrections(items, sentence)


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
