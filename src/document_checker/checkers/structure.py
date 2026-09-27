# -*- coding: utf-8 -*-
"""结构类检查器：页码、标题序号、秘级、附件、落款（印章位置走 VLM，预留）。"""
from __future__ import annotations

import re

from . import register, Finding
from ..docx_parser import normalize_font

LEVEL_PATTERNS = {
    1: (re.compile(r"^[一二三四五六七八九十百]+、"), "一、"),
    2: (re.compile(r"^（[一二三四五六七八九十百]+）"), "（一）"),
    3: (re.compile(r"^\d+\."), "1."),
    4: (re.compile(r"^（\d+）"), "（1）"),
}
TRAILING_PUNCT = "，。；、：；,.;:"


@register("page_number")
def page_number(model, roles, params):
    """页码格式。params: dash, alignment, fonts, size_pt, footer_distance_cm, tolerance_cm"""
    findings = []
    dash = params.get("dash", "—")
    if not model.footer_paras:
        return [Finding(location="页脚", message="未找到页脚（页码缺失）",
                        expected=f"页码格式「{dash} 1 {dash}」", actual="无页脚",
                        suggestion="插入 → 页码，格式设为「— 1 —」并居中")]
    for fp in model.footer_paras:
        if not fp.has_page_field:
            findings.append(Finding(location="页脚", message="页脚中未检测到自动页码域（PAGE）",
                                    expected="自动页码域", actual="无",
                                    suggestion="页码必须是自动页码域，不要手打数字"))
        else:
            pat = rf"^\s*{re.escape(dash)}\s*\d*\s*{re.escape(dash)}\s*$"
            if not re.match(pat, fp.text):
                findings.append(Finding(
                    location="页脚", message="页码格式不符合要求",
                    expected=f"「{dash} 1 {dash}」", actual=f"「{fp.text.strip()}」",
                    suggestion=f"页码两侧使用一字线「{dash}」，不要用短横线"))
        if params.get("alignment") == "center" and fp.alignment != "CENTER":
            findings.append(Finding(location="页脚", message="页码未左右居中",
                                    expected="居中", actual=fp.alignment or "居左/默认",
                                    suggestion="页脚段落设为居中"))
        exp_size = params.get("size_pt")
        fonts = {normalize_font(f) for f in params.get("fonts", [])}
        for r in fp.runs:
            if not r.text.strip():
                continue
            if fonts and normalize_font(r.font_ea or r.font_ascii) not in fonts:
                findings.append(Finding(location="页脚", message="页码字体不符合要求",
                                        expected=params["fonts"][0],
                                        actual=(r.font_ea or r.font_ascii) or "未设置"))
            if exp_size and (r.size_pt is None or abs(r.size_pt - exp_size) > 0.01):
                findings.append(Finding(location="页脚", message="页码字号不符合要求",
                                        expected=f"{exp_size} 磅",
                                        actual=f"{r.size_pt} 磅" if r.size_pt else "未设置"))
            break  # 页脚字体检查一个代表 run 即可
    exp_fd = params.get("footer_distance_cm")
    if exp_fd:
        tol = params.get("tolerance_cm", 0.1)
        for si, sec in enumerate(model.sections):
            if sec.footer_distance_cm is None or abs(sec.footer_distance_cm - exp_fd) > tol:
                findings.append(Finding(
                    location=f"第{si + 1}节" if len(model.sections) > 1 else "页面设置",
                    message="页脚底端距离不符合要求",
                    expected=f"{exp_fd} cm",
                    actual="未设置" if sec.footer_distance_cm is None else f"{sec.footer_distance_cm} cm",
                    suggestion=f"页面布局 → 页脚距边界 → 设为 {exp_fd} 厘米"))
    return findings


@register("heading_number")
def heading_number(model, roles, params):
    """标题序号：层级编号形式 + 三/四级编号右侧不空格。"""
    findings = []
    for lvl, (pat, example) in LEVEL_PATTERNS.items():
        for i in roles.get(f"heading{lvl}", []):
            p = model.paragraphs[i]
            t = p.text.strip()
            m = pat.match(t)
            if not m:
                findings.append(Finding(
                    location=f"第{i + 1}段「{p.snippet()}」",
                    message=f"{lvl}级标题编号形式不符合要求",
                    expected=f"形如「{example}」", actual=f"「{t[:6]}」",
                    suggestion=f"{lvl}级标题编号应使用「{example}」形式"))
            elif lvl in (3, 4):
                rest = t[m.end():]
                if rest[:1] in (" ", "　"):
                    findings.append(Finding(
                        location=f"第{i + 1}段「{p.snippet()}」",
                        message=f"{lvl}级标题编号右侧不应空格",
                        expected=f"「{example}标题」顶格连写", actual=f"「{t[:8]}」",
                        suggestion="删除编号与标题文字之间的空格"))
    # 正文里的可疑编号（如一级标题误用 "1、"）
    for i in roles.get("body", []):
        t = model.paragraphs[i].text.strip()
        if re.match(r"^\d+、", t):
            findings.append(Finding(
                location=f"第{i + 1}段「{model.paragraphs[i].snippet()}」",
                message="疑似标题编号层级错误（正文中出现「数字+顿号」）",
                expected="一级标题应为「一、」", actual=f"「{t[:6]}」",
                suggestion="若为一级标题请改为「一、」；若为正文列举请确认层级"))
    return findings


@register("secrecy")
def secrecy(model, roles, params):
    """秘级：位置（首页左上角顶格）、字体字号加粗、"秘密"二字间空一格。
    params: fonts, size_pt, bold, inner_space, required
    """
    idxs = roles.get("secrecy", [])
    if not idxs:
        if params.get("required"):
            return [Finding(location="文档开头", message="缺少秘级标注",
                            expected="顶格编排于版心左上角", actual="缺失")]
        return []
    i = idxs[0]
    p = model.paragraphs[i]
    findings = []
    loc = f"第{i + 1}段「{p.snippet()}」"
    before = [q for q in model.paragraphs[:i] if not q.is_blank]
    if before:
        findings.append(Finding(location=loc, message="秘级应置于文档首个非空段落",
                                expected="版心左上角顶格", actual=f"其前还有 {len(before)} 个非空段"))
    if p.alignment not in (None, "LEFT"):
        findings.append(Finding(location=loc, message="秘级应顶格居左",
                                expected="居左", actual=p.alignment,
                                suggestion="取消居中，左对齐且不留缩进"))
    fonts = {normalize_font(f) for f in params.get("fonts", [])}
    r = p.main_run()
    if r:
        if fonts and normalize_font(r.font_ea) not in fonts:
            findings.append(Finding(location=loc, message="秘级字体不符合要求",
                                    expected=params["fonts"][0], actual=r.font_ea or "未设置"))
        size = params.get("size_pt")
        if size and (r.size_pt is None or abs(r.size_pt - size) > 0.01):
            findings.append(Finding(location=loc, message="秘级字号不符合要求",
                                    expected=f"{size} 磅",
                                    actual=f"{r.size_pt} 磅" if r.size_pt else "未设置"))
        if params.get("bold") and not r.bold:
            findings.append(Finding(location=loc, message="秘级应加粗",
                                    expected="加粗", actual="未加粗"))
    if params.get("inner_space"):
        t = p.text.strip()
        if re.match(r"^(秘密|机密|绝密)", t) and not re.match(r"^.\s+.", t):
            findings.append(Finding(location=loc, message="秘级两字之间应空一格",
                                    expected="「秘 密」", actual=f"「{t}」",
                                    suggestion="两个字之间加一个空格"))
    return findings


@register("attachment")
def attachment(model, roles, params):
    """附件说明：左空两字、前文空行、名称后不加标点。params: indent_chars, blank_lines_before, forbid_trailing_punct"""
    idxs = roles.get("attachment", [])
    if not idxs:
        return []
    findings = []
    want_blank = params.get("blank_lines_before", 1)
    for i in idxs:
        p = model.paragraphs[i]
        loc = f"第{i + 1}段「{p.snippet()}」"
        raw = p.text
        indent_ok = raw.startswith("  ") or raw.startswith("　") or p.first_line_chars == 200
        if not indent_ok:
            findings.append(Finding(location=loc, message="「附件」应左空两字编排",
                                    expected="左空两字", actual="未留空",
                                    suggestion="段首加两个汉字宽度的空格或设置缩进"))
        if params.get("forbid_trailing_punct") and raw.strip()[-1:] in TRAILING_PUNCT:
            findings.append(Finding(location=loc, message="附件名称后不应加标点符号",
                                    expected="无结尾标点", actual=f"结尾为「{raw.strip()[-1]}」",
                                    suggestion="删除附件名称末尾的标点"))
        j, blanks = i - 1, 0
        while j >= 0 and model.paragraphs[j].is_blank:
            blanks += 1
            j -= 1
        if blanks < want_blank:
            findings.append(Finding(location=loc, message="附件说明前应与正文空行",
                                    expected=f"空 {want_blank} 行", actual=f"空 {blanks} 行"))
    return findings


@register("signature")
def signature(model, roles, params):
    """落款：署名/成文日期存在性、顺序、日期写法、下空行数；印章位置为 VLM 预留。
    params: date_format(chinese), blank_lines_before, seal_expected
    """
    findings = []
    sig = roles.get("signature", [])
    date = roles.get("date", [])
    if not sig:
        findings.append(Finding(location="文末", message="未找到发文机关署名",
                                expected="正文或附件说明下空二行处", actual="缺失"))
    if not date:
        findings.append(Finding(location="文末", message="未找到成文日期",
                                expected="署名下另起一行", actual="缺失"))
    if sig and date:
        if date[0] < sig[0]:
            findings.append(Finding(location="文末", message="成文日期应在发文机关署名的下一行",
                                    expected="署名在上、日期在下", actual="顺序相反"))
        t = model.paragraphs[date[0]].text.strip()
        if params.get("date_format") == "chinese" and not re.match(r"^\d{4}年\d{1,2}月\d{1,2}日$", t):
            findings.append(Finding(
                location=f"第{date[0] + 1}段「{t}」",
                message="成文日期写法不符合要求",
                expected="阿拉伯数字全称，如「2026年9月18日」", actual=f"「{t}」",
                suggestion="改为「YYYY年M月D日」，不要用点号或短横分隔"))
        want_blank = params.get("blank_lines_before", 2)
        j, blanks = sig[0] - 1, 0
        while j >= 0 and model.paragraphs[j].is_blank:
            blanks += 1
            j -= 1
        if blanks != want_blank:
            findings.append(Finding(
                location=f"第{sig[0] + 1}段「{model.paragraphs[sig[0]].snippet()}」",
                message="署名与正文/附件说明之间的空行数不符合要求",
                expected=f"下空 {want_blank} 行", actual=f"空 {blanks} 行",
                severity="warning"))
    if params.get("seal_expected"):
        if model.inline_image_count == 0:
            findings.append(Finding(location="文末", message="规则要求盖章但未检测到印章图片",
                                    expected="发文机关署名处加盖印章", actual="无图片",
                                    severity="warning"))
        else:
            findings.append(Finding(
                location="文末", severity="info",
                message="已检测到图片（疑似印章）；印章位置（端正、居中下压署名与成文日期）需 VLM 复核",
                suggestion="VLM 印章位置检查接口已预留，接入 Word→PDF 渲染后启用"))
    return findings
