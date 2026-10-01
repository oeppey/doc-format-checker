# -*- coding: utf-8 -*-
"""Correction adapters and strict validation of model proposals."""
from __future__ import annotations

import json
import os
import re

from .filters import PROTECTED_TERMS
from .confusion import WRONG2RIGHT

SYSTEM_PROMPT = """你是公文错别字检查器。只检查并修正错别字（同音字、形近字、多字、漏字、叠字）。
只改错别字，不改标点、用词风格、专有名词或法律术语。
输出 JSON 数组，每项为 {"原文":"句中连续片段","改为":"修改后片段","理由":"一句话"}。
没有错误时输出 []。不要输出 JSON 以外的内容。"""


class CorrectionRejected(ValueError):
    """模型给出了回答但内容未通过校验（改写幅度、JSON 结构、保护词等）。

    与服务故障（HTTP/连接/响应结构无效）区分：被拒绝的句子已经过
    初筛与词表兜底检查，不计入精检失败，按低置信建议过滤并留痕。
    """


def _edit_distance(a: str, b: str, limit: int = 1) -> int:
    """Bounded Levenshtein distance; values above limit need no exact result."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(
                current[-1] + 1, previous[j] + 1,
                previous[j - 1] + (ca != cb),
            ))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _overlaps_protected(sentence: str, src: str, offset: int | None = None) -> bool:
    spans = ([m.span() for m in re.finditer(re.escape(src), sentence)]
             if offset is None else [(offset, offset + len(src))])
    for start, end in spans:
        for term in PROTECTED_TERMS:
            for match in re.finditer(re.escape(term), sentence):
                ps, pe = match.span()
                if (start < pe and ps < end) or (not src and ps < start < pe):
                    return True
    return False


def validate_corrections(items: object, sentence: str) -> list[dict]:
    if not isinstance(items, list):
        raise CorrectionRejected("精检结果必须是 JSON 数组")
    valid = []
    for item in items:
        if not isinstance(item, dict):
            raise CorrectionRejected("精检数组元素必须是对象")
        src, dst = item.get("原文"), item.get("改为")
        offset = item.get("offset")
        if not isinstance(src, str) or not isinstance(dst, str) or (not src and not dst):
            raise CorrectionRejected("精检结果缺少有效的原文或改为字段")
        if offset is not None:
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                raise CorrectionRejected("精检位置无效")
            if offset > len(sentence) or sentence[offset:offset + len(src)] != src:
                raise CorrectionRejected("精检位置与原句不符")
        elif not src or src not in sentence:
            raise CorrectionRejected(f"建议片段不在原句中或未发生修改：{src!r}")
        if src == dst:
            raise CorrectionRejected(f"建议片段未发生修改：{src!r}")
        if len(src) > 12 or _edit_distance(src, dst) > 1:
            raise CorrectionRejected(f"建议超出单处错别字修改范围：{src!r} → {dst!r}")
        if _overlaps_protected(sentence, src, offset):
            raise CorrectionRejected(f"建议改动受保护术语：{src!r}")
        result = {"原文": src, "改为": dst, "理由": str(item.get("理由", ""))}
        if offset is not None:
            result["offset"] = offset
        valid.append(result)
    return valid


def _parse_and_validate(raw: str, sentence: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        items = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorrectionRejected(f"精检结果不是有效 JSON：{exc}") from exc
    return validate_corrections(items, sentence)


class LLMCorrector:
    """Compatibility entry point for the explicit OpenAI service adapter."""

    def __new__(cls, model: str | None = None, base_url: str | None = None,
                protocol: str | None = None, client=None):
        from .service_corrector import OpenAICorrector
        return OpenAICorrector(model, base_url, protocol, client)


class HeuristicCorrector:
    """Demo fallback based on a small confusion dictionary."""

    def correct(self, sentence: str, suspect_chars=None) -> list[dict]:
        items = [
            {"原文": wrong, "改为": right, "理由": "混淆词表命中"}
            for wrong, right in WRONG2RIGHT.items() if wrong in sentence
        ]
        return validate_corrections(items, sentence)
