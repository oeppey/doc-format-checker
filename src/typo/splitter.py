# -*- coding: utf-8 -*-
"""按句子拆分（保留原文偏移量，供错字定位）。"""
from __future__ import annotations

from dataclasses import dataclass

SENT_END = "。！？；\n"
CLAUSE_SEP = "，、："
CLAUSE_MIN_LEN = 60   # 超过才切成短句


@dataclass
class Sentence:
    para_index: int
    start: int          # 在段落内的起始偏移
    end: int
    text: str


def split_text(text: str):
    """把一段文本切成句子，返回 (start, end, 子串)，结束标点随句。"""
    spans = []
    start = 0
    for i, ch in enumerate(text):
        if ch in SENT_END:
            if text[start:i + 1].strip():
                spans.append((start, i + 1))
            start = i + 1
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans


def split_paragraph(para_index: int, text: str) -> list[Sentence]:
    out = []
    for s, e in split_text(text):
        seg = text[s:e]
        if len(seg) > CLAUSE_MIN_LEN:
            # 长句再按逗号/顿号/冒号切成短句，偏移量保持一致
            for cs, ce in split_text_keep_offset(seg, CLAUSE_SEP):
                out.append(Sentence(para_index, s + cs, s + ce, seg[cs:ce]))
        else:
            out.append(Sentence(para_index, s, e, seg))
    return out


def split_text_keep_offset(text: str, seps: str):
    spans = []
    start = 0
    for i, ch in enumerate(text):
        if ch in seps:
            if text[start:i + 1].strip():
                spans.append((start, i + 1))
            start = i + 1
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans
