# -*- coding: utf-8 -*-
"""Word 文档解析层。

把 python-docx 的对象模型拍平成与格式检查无关的数据结构（DocModel），
所有检查器只依赖本模块的数据结构，不直接碰 python-docx，便于以后换解析实现。

注意：python-docx 只读 run 级显式属性，样式继承只做了"段落样式"一层兜底，
真实公文字体写在不规范的位置（如只设在样式上）时需要在真实样本上再验证。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

# 中文字号 → 磅值
CN_FONT_SIZE = {
    "初号": 42, "小初": 36, "一号": 26, "小一": 24, "二号": 22, "小二": 18,
    "三号": 16, "小三": 15, "四号": 14, "小四": 12, "五号": 10.5, "小五": 9,
}


def normalize_font(name: str | None) -> str:
    """字体名归一化：'方正小标宋_GBK' / '方正小标宋GBK' / '方正小标宋简体' 视为一族时
    由规则里的别名列表兜底，这里只做去分隔符 + 小写。"""
    if not name:
        return ""
    return re.sub(r"[\s_\-]+", "", str(name)).lower()


def _align_name(align) -> str | None:
    if align is None:
        return None
    mapping = {
        WD_ALIGN_PARAGRAPH.LEFT: "LEFT",
        WD_ALIGN_PARAGRAPH.CENTER: "CENTER",
        WD_ALIGN_PARAGRAPH.RIGHT: "RIGHT",
        WD_ALIGN_PARAGRAPH.JUSTIFY: "JUSTIFY",
    }
    return mapping.get(align, str(align))


@dataclass
class RunInfo:
    text: str
    font_ea: str | None          # 中文字体（w:rFonts/@w:eastAsia）
    font_ascii: str | None       # 西文字体（w:rFonts/@w:ascii）
    size_pt: float | None
    bold: bool | None
    char_spacing_pt: float | None  # 字符间距（磅，w:rPr/w:spacing，正值=加宽）


@dataclass
class ParaInfo:
    index: int                    # 在文档 body 中的段落序号（0 起，含空段）
    text: str
    style_name: str
    alignment: str | None
    line_pt: float | None         # w:pPr/w:spacing/@w:line 换算成磅
    line_rule: str | None         # exact / auto / atLeast ...
    first_line_chars: int | None  # 首行缩进（字符数×100，200=两字符）
    right_chars: int | None       # 右侧缩进（字符数×100）
    runs: list[RunInfo] = field(default_factory=list)

    @property
    def is_blank(self) -> bool:
        return self.text.strip() == ""

    def content_runs(self) -> list[RunInfo]:
        return [r for r in self.runs if r.text.strip()]

    def main_run(self) -> RunInfo | None:
        crs = self.content_runs()
        return max(crs, key=lambda r: len(r.text)) if crs else None

    def main_size(self) -> float | None:
        r = self.main_run()
        return r.size_pt if r else None

    def snippet(self, n: int = 14) -> str:
        t = self.text.strip().replace("\n", " ")
        return t[:n] + ("…" if len(t) > n else "")


@dataclass
class FooterPara:
    text: str              # 含域结果文本的完整拼接（如 "— 1 —"）
    alignment: str | None
    has_page_field: bool
    runs: list[RunInfo] = field(default_factory=list)


@dataclass
class SectionInfo:
    top_cm: float | None
    bottom_cm: float | None
    left_cm: float | None
    right_cm: float | None
    footer_distance_cm: float | None


@dataclass
class DocModel:
    path: str
    paragraphs: list[ParaInfo]
    sections: list[SectionInfo]
    footer_paras: list[FooterPara]
    inline_image_count: int


def _parse_run(run) -> RunInfo:
    el = run._element
    rPr = el.rPr
    font_ea = font_ascii = None
    char_spacing = None
    if rPr is not None:
        rf = rPr.find(qn("w:rFonts"))
        if rf is not None:
            font_ea = rf.get(qn("w:eastAsia"))
            font_ascii = rf.get(qn("w:ascii"))
        sp = rPr.find(qn("w:spacing"))
        if sp is not None and sp.get(qn("w:val")):
            char_spacing = int(sp.get(qn("w:val"))) / 20.0
    # 样式兜底：run 未显式设置时取段落样式
    style = run._parent.style if run._parent is not None else None
    size = run.font.size.pt if run.font.size else None
    if size is None and style is not None and getattr(style.font, "size", None):
        size = style.font.size.pt
    if font_ea is None and style is not None:
        srf = style.element.find(qn("w:rPr") + "/" + qn("w:rFonts"))
        if srf is not None:
            font_ea = srf.get(qn("w:eastAsia"))
    return RunInfo(
        text=run.text or "",
        font_ea=font_ea,
        font_ascii=font_ascii or run.font.name,
        size_pt=size,
        bold=run.font.bold,
        char_spacing_pt=char_spacing,
    )


def _parse_paragraph(p, index: int) -> ParaInfo:
    pPr = p._p.pPr
    line_pt = line_rule = None
    first_line_chars = right_chars = None
    if pPr is not None:
        sp = pPr.find(qn("w:spacing"))
        if sp is not None and sp.get(qn("w:line")):
            line_pt = int(sp.get(qn("w:line"))) / 20.0
            line_rule = sp.get(qn("w:lineRule")) or "auto"
        ind = pPr.find(qn("w:ind"))
        if ind is not None:
            if ind.get(qn("w:firstLineChars")):
                first_line_chars = int(ind.get(qn("w:firstLineChars")))
            if ind.get(qn("w:rightChars")):
                right_chars = int(ind.get(qn("w:rightChars")))
    return ParaInfo(
        index=index,
        text=p.text or "",
        style_name=p.style.name if p.style is not None else "",
        alignment=_align_name(p.paragraph_format.alignment),
        line_pt=line_pt,
        line_rule=line_rule,
        first_line_chars=first_line_chars,
        right_chars=right_chars,
        runs=[_parse_run(r) for r in p.runs],
    )


def _parse_footer_para(p) -> FooterPara:
    el = p._p
    # 完整文本要包含域结果（fldSimple 里的 w:t 不在 p.runs 里）
    full_text = "".join(t.text or "" for t in el.findall(".//" + qn("w:t")))
    has_page = any(
        "PAGE" in (it.text or "") for it in el.findall(".//" + qn("w:instrText"))
    ) or any(
        "PAGE" in (f.get(qn("w:instr")) or "") for f in el.findall(".//" + qn("w:fldSimple"))
    )
    return FooterPara(
        text=full_text,
        alignment=_align_name(p.paragraph_format.alignment),
        has_page_field=has_page,
        runs=[_parse_run(r) for r in p.runs],
    )


def parse_document(path: str) -> DocModel:
    doc = Document(path)
    paragraphs = [_parse_paragraph(p, i) for i, p in enumerate(doc.paragraphs)]

    sections: list[SectionInfo] = []
    footer_paras: list[FooterPara] = []
    for sec in doc.sections:
        def cm(v):
            return round(v.cm, 3) if v is not None else None
        sections.append(SectionInfo(
            top_cm=cm(sec.top_margin),
            bottom_cm=cm(sec.bottom_margin),
            left_cm=cm(sec.left_margin),
            right_cm=cm(sec.right_margin),
            footer_distance_cm=cm(sec.footer_distance),
        ))
        ftr = sec.footer
        if ftr is not None and not ftr.is_linked_to_previous:
            footer_paras.extend(_parse_footer_para(p) for p in ftr.paragraphs)

    return DocModel(
        path=path,
        paragraphs=paragraphs,
        sections=sections,
        footer_paras=footer_paras,
        inline_image_count=len(doc.inline_shapes),
    )
