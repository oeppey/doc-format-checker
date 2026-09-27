# -*- coding: utf-8 -*-
"""合成数据生成器（内容与格式解耦版）。

- build_doc(doc_type, out_path, content=None, violations=None)
- content 为 None 时用内置模板；也可由 import_docx 从真实公文抽取后灌入
- content 结构：
    {
      "title": str,
      "blocks": [("h1"|"h2"|"h3"|"body", 文本), ...],
      "attachment": str | None,     # 附件说明行（不含"附件："前的空格）
      "signature": str, "date": str,
      "secrecy": bool,              # 是否生成秘级行
    }
- violations：违规注入，用于验证检查器（合规样本应零误报，注入项应全检出）
"""
from __future__ import annotations

import copy

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

# ---------------------------------------------------------------- 基准格式配置
BASE_CONFIG = {
    "dazi": {
        "desc": "呈报稿（大字版）",
        "margins": {"top": 3.8, "bottom": 3.3, "left": 2.7, "right": 2.7},
        "footer_distance": 1.75,
        "line_pt": 32.0,
        "char_spacing_pt": 0.4,
        "secrecy": {"text": "秘 密", "font": "方正黑体_GBK", "size": 18, "bold": True},
        "title": {"font": "方正小标宋_GBK", "size": 24, "bold": True},
        "body": {"font": "方正仿宋_GBK", "size": 18, "bold": True},
        "h1": {"font": "方正黑体_GBK", "size": 18, "bold": True},
        "h2": {"font": "方正楷体_GBK", "size": 18, "bold": True},
        "h3": {"font": "方正仿宋_GBK", "size": 18, "bold": True},
        "page_num": {"dash": "—", "font": "宋体", "size": 14, "center": True},
    },
    "xiaozi": {
        "desc": "呈报稿（小字版）",
        "margins": {"top": 3.8, "bottom": 3.3, "left": 2.7, "right": 2.7},
        "footer_distance": 1.75,
        "line_pt": 29.5,
        "char_spacing_pt": 0.0,
        "secrecy": {"text": "秘 密", "font": "方正黑体_GBK", "size": 16, "bold": True},
        "title": {"font": "方正小标宋_GBK", "size": 22, "bold": False},
        "body": {"font": "方正仿宋_GBK", "size": 16, "bold": False},
        "h1": {"font": "方正黑体_GBK", "size": 16, "bold": False},
        "h2": {"font": "方正楷体_GBK", "size": 16, "bold": False},
        "h3": {"font": "方正仿宋_GBK", "size": 16, "bold": False},
        "page_num": {"dash": "—", "font": "宋体", "size": 14, "center": True},
    },
}

# ---------------------------------------------------------------- 内置内容模板
DEFAULT_CONTENT = {
    "title": "关于XX专项工作进展情况的报告",
    "blocks": [
        ("h1", "一、工作开展情况"),
        ("body", "今年以来，我室按照委机关统一部署，扎实推进XX专项工作，取得阶段性成效。现将有关情况报告如下。"),
        ("h2", "（一）加强组织领导"),
        ("body", "成立专项工作专班，明确责任分工，制定实施方案，确保各项任务有序推进、落细落地。"),
        ("h3", "1.健全工作机制"),
        ("body", "建立周调度、月通报工作机制，及时研究解决工作推进中的难点堵点问题。"),
        ("h1", "二、下一步工作安排"),
        ("body", "持续深化专项治理，强化跟踪问效，确保高质量完成年度目标任务。"),
    ],
    "attachment": "1.XX专项工作实施方案",
    "signature": "泰州市纪委监委XX室",
    "date": "2026年9月18日",
    "secrecy": True,
}


# ---------------------------------------------------------------- 底层写入
def _set_font(run, cn_font, size_pt, bold, spacing_pt=None):
    run.font.name = "仿宋"          # 西文字体统一仿宋（注意事项第3条）
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), cn_font)
    if spacing_pt:
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:val"), str(int(spacing_pt * 20)))
        rPr.append(sp)


def _set_exact_line(p, pt):
    pPr = p._p.get_or_add_pPr()
    sp = pPr.find(qn("w:spacing"))
    if sp is None:
        sp = OxmlElement("w:spacing")
        pPr.append(sp)
    sp.set(qn("w:line"), str(int(pt * 20)))
    sp.set(qn("w:lineRule"), "exact")


def _set_first_line_chars(p, chars=200):
    pPr = p._p.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)
    ind.set(qn("w:firstLineChars"), str(chars))
    ind.set(qn("w:firstLine"), str(int(chars / 100 * 18 * 20)))  # 兜底：按18磅字估算


def _set_right_chars(p, chars=200):
    pPr = p._p.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)
    ind.set(qn("w:rightChars"), str(chars))


def _add_page_field(para, result_text="1"):
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), r" PAGE   \* MERGEFORMAT ")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = result_text
    r.append(t)
    fld.append(r)
    para._p.append(fld)


# ---------------------------------------------------------------- 生成
def build_doc(cfg: dict, out_path: str, content: dict | None = None,
              mutations: list[str] | None = None) -> list[str]:
    """按配置生成一份文档。cfg 由 synth.golden.build_cfg 从规则 YAML 推导；
    mutations 为变异名列表（见 synth.mutations）。"""
    from .mutations import apply_mutations

    cfg = copy.deepcopy(cfg)
    content = copy.deepcopy(content or DEFAULT_CONTENT)
    applied = apply_mutations(cfg, content, mutations or [])

    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Cm(cfg["margins"]["top"])
    sec.bottom_margin = Cm(cfg["margins"]["bottom"])
    sec.left_margin = Cm(cfg["margins"]["left"])
    sec.right_margin = Cm(cfg["margins"]["right"])
    sec.footer_distance = Cm(cfg["footer_distance"])

    # 页脚：— 1 —
    footer = sec.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER if cfg["page_num"]["center"] else WD_ALIGN_PARAGRAPH.RIGHT
    for r in list(fp.runs):
        r._element.getparent().remove(r._element)
    dash = cfg["page_num"]["dash"]
    r1 = fp.add_run(f"{dash} ")
    _set_font(r1, cfg["page_num"]["font"], cfg["page_num"]["size"], False)
    _add_page_field(fp, "1")
    r2 = fp.add_run(f" {dash}")
    _set_font(r2, cfg["page_num"]["font"], cfg["page_num"]["size"], False)

    line_pt = cfg["line_pt"]
    cs = cfg["char_spacing_pt"]

    # 秘级
    if content.get("secrecy"):
        s = cfg["secrecy"]
        p = doc.add_paragraph()
        _set_exact_line(p, line_pt)
        _set_font(p.add_run(s["text"]), s["font"], s["size"], s["bold"], cs)

    # 标题
    t = cfg["title"]
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_exact_line(p, line_pt)
    _set_font(p.add_run(content["title"]), t["font"], t["size"], t["bold"], cs)

    # 正文与各级标题
    for kind, text in content["blocks"]:
        p = doc.add_paragraph()
        _set_exact_line(p, line_pt)
        f = cfg[kind]
        if kind == "body":
            _set_first_line_chars(p, 200)
        _set_font(p.add_run(text), f["font"], f["size"], f["bold"], cs)

    # 附件说明（正文下空一行、左空两字）
    if content.get("attachment"):
        doc.add_paragraph()
        p = doc.add_paragraph()
        _set_exact_line(p, line_pt)
        b = cfg["body"]
        _set_font(p.add_run("  附件：" + content["attachment"]), b["font"], b["size"], b["bold"], cs)

    # 落款（下空二行，右空二字）
    doc.add_paragraph()
    doc.add_paragraph()
    b = cfg["body"]
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _set_exact_line(p, line_pt)
    _set_right_chars(p, 200)
    _set_font(p.add_run(content["signature"]), b["font"], b["size"], b["bold"], cs)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _set_exact_line(p, line_pt)
    _set_right_chars(p, 200)
    _set_font(p.add_run(content["date"]), b["font"], b["size"], b["bold"], cs)

    doc.save(out_path)
    return applied
