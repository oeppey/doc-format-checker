# -*- coding: utf-8 -*-
"""启发式过滤：无需检查/极易误报的内容不进检测器。

两层：
  - should_skip(sentence)：整句跳过（文号、日期行、页码行、非中文为主等）
  - PROTECTED_TERMS：法律/公文专名，句子照查，但纠错结果若改动这些词则丢弃
    （通用纠错模型最爱把"定金"改成"订金"、把"不起诉"改成"起诉"，必须拦住）
"""
from __future__ import annotations

import re

WENHAO_RE = re.compile(r"〔\s*\d{4}\s*〕\s*[\d＊*]*\s*号?$")
DATE_LINE_RE = re.compile(r"^\d{4}\s*[年./\-]\s*\d{1,2}\s*[月./\-]\s*\d{1,2}\s*日?$")
PAGE_LINE_RE = re.compile(r"^[—\-–\s]*\d+[—\-–\s]*$")
ID_NUMBER_RE = re.compile(r"\d{15,18}[0-9Xx]?")
CJK_RE = re.compile(r"[一-鿿]")

# 法律/公文专名保护表（纠错结果校验用，可按需扩充或外置 YAML）
PROTECTED_TERMS = [
    "定金", "订金", "不起诉", "免于起诉", "缓刑", "假释", "减刑", "取保候审",
    "监视居住", "刑事拘留", "行政拘留", "犯罪嫌疑人", "被告人", "被害人",
    "法定代理人", "利害关系人", "第三人", "再审", "申诉", "抗诉", "上诉",
    "裁定", "判决", "调解", "仲裁", "听证", "留置", "双规", "诫勉",
    "党纪", "政务处分", "警告处分", "严重警告", "撤销党内职务", "留党察看",
    "开除党籍", "移送司法机关", "违法所得", "违纪所得",
]


def cjk_ratio(text: str) -> float:
    stripped = re.sub(r"\s", "", text)
    if not stripped:
        return 0.0
    return len(CJK_RE.findall(stripped)) / len(stripped)


def should_skip(text: str) -> str | None:
    """返回跳过原因；不跳过返回 None。"""
    t = text.strip().strip("。；，、")
    if len(t) < 4:
        return "过短"
    if cjk_ratio(t) < 0.6:
        return "非中文为主"
    if WENHAO_RE.search(t):
        return "文号行"
    if DATE_LINE_RE.match(t):
        return "日期行"
    if PAGE_LINE_RE.match(t):
        return "页码行"
    if ID_NUMBER_RE.fullmatch(t):
        return "证件号码"
    return None
