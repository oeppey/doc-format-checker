# -*- coding: utf-8 -*-
"""变异注册表：每个案例 = 单点违规 + 期望命中的规则（Gold 标注）。

expected_findings 填规则 YAML 里的规则 id；断言方式为"期望 ⊆ 实际"，
允许检查器额外给出相关的细节 finding，但不允许期望的规则不命中。
"""
from __future__ import annotations


def _m_title_font(cfg, content):
    cfg["title"]["font"] = "宋体"

def _m_body_font(cfg, content):
    cfg["body"]["font"] = "宋体"

def _m_body_size(cfg, content):
    cfg["body"]["size"] -= 2

def _m_heading_bold(cfg, content):
    cfg["h1"]["bold"] = not cfg["h1"]["bold"]

def _m_margin(cfg, content):
    cfg["margins"]["left"] = 3.17

def _m_spacing(cfg, content):
    cfg["line_pt"] = 28.0

def _m_char_spacing(cfg, content):
    cfg["char_spacing_pt"] = 0.0 if cfg["char_spacing_pt"] else 0.4

def _m_page_number(cfg, content):
    cfg["page_num"]["dash"] = "-"
    cfg["page_num"]["center"] = False

def _m_heading_num(cfg, content):
    for i, (kind, text) in enumerate(content["blocks"]):
        if kind == "h1":
            content["blocks"][i] = ("h1", "1、" + text.split("、", 1)[-1])
            return

def _m_attachment_punct(cfg, content):
    if content.get("attachment"):
        content["attachment"] += "；"

def _m_date_format(cfg, content):
    content["date"] = "2026.9.18"

def _m_secrecy_bold(cfg, content):
    cfg["secrecy"]["bold"] = False


MUTATIONS = {
    "title_font":       {"desc": "标题字体错（→宋体）",        "fn": _m_title_font,       "expected": ["font-title"]},
    "body_font":        {"desc": "正文字体错（→宋体）",        "fn": _m_body_font,        "expected": ["font-body"]},
    "body_size":        {"desc": "正文字号错（小两号）",       "fn": _m_body_size,        "expected": ["font-body"]},
    "heading_bold":     {"desc": "一级标题加粗状态错误",             "fn": _m_heading_bold,     "expected": ["font-heading-1"]},
    "margin":           {"desc": "左边距错（2.7→3.17cm）",     "fn": _m_margin,           "expected": ["page-setup"]},
    "spacing":          {"desc": "行距错（→28磅）",            "fn": _m_spacing,          "expected": ["line-spacing"]},
    "char_spacing":     {"desc": "字符间距错（标准／加宽互换）",        "fn": _m_char_spacing,     "expected": ["char-spacing"]},
    "page_number":      {"desc": "页码格式错（- 1 - 且未居中）","fn": _m_page_number,      "expected": ["page-number"]},
    "heading_num":      {"desc": "一级标题序号错（一、→1、）", "fn": _m_heading_num,      "expected": ["heading-number"]},
    "attachment_punct": {"desc": "附件名称后多标点",           "fn": _m_attachment_punct, "expected": ["attachment-format"]},
    "date_format":      {"desc": "成文日期写法错（2026.9.18）","fn": _m_date_format,      "expected": ["signature-layout"]},
    "secrecy_bold":     {"desc": "秘级未加粗",                 "fn": _m_secrecy_bold,     "expected": ["secrecy-format"]},
}

# 旧版 --violate 名称兼容
ALIASES = {"line_spacing": "spacing", "margin_left": "margin"}


def resolve(name: str) -> str:
    return ALIASES.get(name, name)


def apply_mutations(cfg, content, names: list[str]) -> list[str]:
    applied = []
    for n in names:
        key = resolve(n)
        if key not in MUTATIONS:
            raise KeyError(f"未知变异：{n}，可选：{list(MUTATIONS)}")
        MUTATIONS[key]["fn"](cfg, content)
        applied.append(f"{key}（{MUTATIONS[key]['desc']}）")
    return applied
