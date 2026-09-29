# -*- coding: utf-8 -*-
"""语义角色映射：判断每个段落属于什么角色（标题/正文/一级标题/署名……）。

三级漏斗，与技术方案一致：
  1. Word 样式 / 大纲级别直接映射（Heading 1、标题 等）
  2. 文本正则 + 位置 + 格式启发式映射
  3. LLM 语义分析（预留接口 map_roles_llm，当前版本未接入）

输出：
  roles:     {role: [para_index, ...]}
  para_role: {para_index: role}
"""
from __future__ import annotations

import re

from .docx_parser import DocModel, normalize_font

SECRECY_RE = re.compile(r"^(绝密|机密|秘\s*密)")
H1_RE = re.compile(r"^[一二三四五六七八九十百]+、")
H2_RE = re.compile(r"^（[一二三四五六七八九十百]+）")
H3_RE = re.compile(r"^\d+\.")
H4_RE = re.compile(r"^（\d+）")
ATTACH_RE = re.compile(r"^\s*附件\s*[:：]")
# 宽匹配：兼容错误写法（2026.9.18 / 2026-09-18 等），角色先归对，写法交给检查器判
DATE_RE = re.compile(r"^\d{4}\s*[年./\-]\s*\d{1,2}\s*[月./\-]\s*\d{1,2}\s*日?$")
WENHAO_RE = re.compile(r"〔\s*\d{4}\s*〕|（\s*\d{4}\s*）|[\(\[]\s*\d{4}\s*[\)\]]")
STYLE_HEADING_RE = re.compile(r"(?:Heading|标题)\s*(\d)")

# 字体启发式：主字体包含关键词 → 疑似标题级别
FONT_HINTS = [("黑体", "heading1"), ("楷体", "heading2")]


def map_roles(model: DocModel):
    paras = model.paragraphs
    roles: dict[str, list[int]] = {}
    para_role: dict[int, str] = {}

    def add(role: str, idx: int):
        roles.setdefault(role, []).append(idx)
        para_role[idx] = role

    non_empty = [p.index for p in paras if not p.is_blank]
    if not non_empty:
        return roles, para_role

    # 1) 密级候选：先识别全文，再由 checker 检查是否放在首页左上角。
    #    只识别首段会让“密级写错位置”被当作普通正文而静默漏检。
    for i in non_empty:
        if SECRECY_RE.match(paras[i].text.strip()):
            add("secrecy", i)

    # 2) 标题：秘级之外的首个非空段
    for i in non_empty:
        if i not in para_role:
            add("title", i)
            break

    # 3) 从尾部找 署名/成文日期（位置强约束，先于编号正则——否则 "2026.9.18" 会被当成三级标题）
    rest = [i for i in non_empty if i not in para_role]
    if rest:
        last = paras[rest[-1]]
        if DATE_RE.match(last.text.strip()):
            add("date", last.index)
            if len(rest) >= 2:
                sig = paras[rest[-2]]
                st = sig.text.strip()
                if len(st) <= 40 and not ATTACH_RE.match(st):
                    add("signature", sig.index)

    # 4) 逐段：样式 → 正则
    for i in non_empty:
        if i in para_role:
            continue
        p = paras[i]
        t = p.text.strip()
        m = STYLE_HEADING_RE.search(p.style_name or "")
        if m:
            add(f"heading{min(int(m.group(1)), 4)}", i)
            continue
        if WENHAO_RE.search(t) and len(t) <= 40:
            add("wenhao", i)
            continue
        if ATTACH_RE.match(p.text):
            add("attachment", i)
            continue
        if H1_RE.match(t):
            add("heading1", i)
            continue
        if H2_RE.match(t):
            add("heading2", i)
            continue
        if H4_RE.match(t):
            add("heading4", i)
            continue
        if H3_RE.match(t):
            add("heading3", i)
            continue

    # 5) 字体启发式兜底：黑体 → 一级标题，楷体 → 二级标题
    #    （覆盖"作者手设格式、没点标题样式、编号又写错"的常见情况）
    for i in non_empty:
        if i in para_role:
            continue
        r = paras[i].main_run()
        if not r:
            continue
        fn = normalize_font(r.font_ea)
        for key, role in FONT_HINTS:
            if key in fn:
                add(role, i)
                break

    # 6) 其余归为正文；空段标记 blank
    for p in paras:
        if p.index not in para_role:
            add("blank" if p.is_blank else "body", p.index)

    return roles, para_role


def map_roles_llm(model: DocModel, roles, para_role):
    """第三级：LLM 语义分析（预留）。

    计划用法：仅把前两级判定不一致或低置信的段落（连同上下文窗口）发给 LLM，
    输出 {"para_index": role} 后覆盖。当前版本未接入，直接原样返回。
    """
    return roles, para_role
