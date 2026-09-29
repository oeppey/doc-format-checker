# -*- coding: utf-8 -*-
"""版式类检查器：页面设置、字体字号、行距、字符间距。"""
from __future__ import annotations

import re

from . import register, Finding
from ..docx_parser import normalize_font

CJK_RE = re.compile(r"[一-鿿]")
ASCII_RE = re.compile(r"[A-Za-z0-9]")


@register("page_setup")
def page_setup(model, roles, params):
    """页面设置：上下左右页边距。params: top_cm/bottom_cm/left_cm/right_cm/tolerance_cm"""
    tol = params.get("tolerance_cm", 0.05)
    findings = []
    items = [("top_cm", "上边距"), ("bottom_cm", "下边距"),
             ("left_cm", "左边距"), ("right_cm", "右边距"),
             ("footer_distance_cm", "页脚距纸张底边")]
    for si, sec in enumerate(model.sections):
        loc = f"第{si + 1}节页面设置" if len(model.sections) > 1 else "页面设置"
        for key, label in items:
            exp = params.get(key)
            if exp is None:
                continue
            act = getattr(sec, key)
            if act is None or abs(act - exp) > tol:
                findings.append(Finding(
                    location=loc,
                    message=f"{label}不符合要求",
                    expected=f"{exp} cm",
                    actual="未设置" if act is None else f"{act} cm",
                    suggestion=f"页面布局 → 页边距 → 将{label}设为 {exp} 厘米",
                ))
    return findings


def _fmt_location(p):
    return f"第{p.index + 1}段「{p.snippet()}」"


@register("font_format")
def font_format(model, roles, params):
    """Check every content run, including mixed Chinese/ASCII runs."""
    role = params["role"]
    idxs = roles.get(role, [])
    if not idxs:
        if params.get("required"):
            return [Finding(location="全文", message=f"未找到角色为「{role}」的段落",
                            expected="应存在该类段落", actual="缺失")]
        return []
    fonts = {normalize_font(f) for f in params.get("fonts", [])}
    ascii_fonts = {normalize_font(f) for f in params.get("ascii_fonts", [])}
    size = params.get("size_pt")
    bold = params.get("bold")
    align = params.get("alignment")
    align_map = {"center": "CENTER", "left": "LEFT", "right": "RIGHT"}
    findings = []
    for i in idxs:
        p = model.paragraphs[i]
        if p.is_blank:
            continue
        loc = _fmt_location(p)
        if align:
            want = align_map[align]
            got = p.alignment or "LEFT"
            if got != want:
                findings.append(Finding(
                    location=loc, message=f"「{role}」对齐方式不符合要求",
                    expected=align, actual=got, suggestion=f"将对齐方式调整为：{align}"))
        for run_index, r in enumerate(p.runs, 1):
            if not r.text.strip():
                continue
            run_loc = f"{loc}（run {run_index}）"
            issues = []
            if fonts and CJK_RE.search(r.text) and "font_ea" not in r.unresolved and normalize_font(r.font_ea) not in fonts:
                issues.append(("中文字体", params["fonts"][0], r.font_ea or "未设置"))
            if ascii_fonts and ASCII_RE.search(r.text) and "font_ascii" not in r.unresolved and normalize_font(r.font_ascii) not in ascii_fonts:
                issues.append(("西文字体", params["ascii_fonts"][0], r.font_ascii or "未设置"))
            if size is not None and (r.size_pt is None or abs(r.size_pt - size) > 0.01):
                issues.append(("字号", f"{size} 磅",
                               f"{r.size_pt} 磅" if r.size_pt is not None else "未设置"))
            if bold is not None and r.bold is not bold:
                issues.append(("加粗", "加粗" if bold else "不加粗",
                               "加粗" if r.bold else ("不加粗" if r.bold is False else "未设置")))
            for what, exp, act in issues:
                findings.append(Finding(
                    location=run_loc, message=f"「{role}」{what}不符合要求",
                    expected=str(exp), actual=str(act),
                    suggestion=f"将{what}调整为：{exp}"))
    return findings


@register("line_spacing")
def line_spacing(model, roles, params):
    """行距（固定值，磅）。params: roles[], line_pt, tolerance_pt"""
    exp = params["line_pt"]
    tol = params.get("tolerance_pt", 0.5)
    findings = []
    for role in params.get("roles", ["body"]):
        for i in roles.get(role, []):
            p = model.paragraphs[i]
            if p.is_blank:
                continue
            ok = p.line_rule == "exact" and p.line_pt is not None and abs(p.line_pt - exp) <= tol
            if not ok:
                if p.line_pt is None:
                    actual = "未设置（单倍行距）"
                elif p.line_rule == "exact":
                    actual = f"固定值 {p.line_pt} 磅"
                elif p.line_rule == "atLeast":
                    actual = f"最小值 {p.line_pt} 磅"
                elif p.line_multiple is not None:
                    actual = f"{p.line_multiple:g} 倍行距"
                else:
                    actual = "行距无法解析"
                findings.append(Finding(
                    location=_fmt_location(p),
                    message=f"「{role}」行距不符合要求",
                    expected=f"固定值 {exp} 磅", actual=actual,
                    suggestion=f"段落 → 行距 → 固定值，设置 {exp} 磅",
                ))
    return findings


@register("char_spacing")
def char_spacing(model, roles, params):
    """Check the effective spacing of every content run."""
    exp = params.get("spacing_pt", 0.0)
    tol = params.get("tolerance_pt", 0.05)
    findings = []
    for role in params.get("roles", ["body"]):
        for i in roles.get(role, []):
            p = model.paragraphs[i]
            for run_index, r in enumerate(p.runs, 1):
                if not r.text.strip():
                    continue
                act = r.char_spacing_pt
                ok = (act is None and abs(exp) <= tol) or (
                    act is not None and abs(act - exp) <= tol)
                if not ok:
                    findings.append(Finding(
                        location=f"{_fmt_location(p)}（run {run_index}）",
                        message=f"「{role}」字符间距不符合要求",
                        expected="标准" if exp == 0 else f"加宽 {exp} 磅",
                        actual="标准" if act is None or act == 0 else f"加宽 {act} 磅",
                        suggestion="字体 → 高级 → 字符间距 → 设为" +
                        ("标准" if exp == 0 else f"加宽 {exp} 磅")))
    return findings
