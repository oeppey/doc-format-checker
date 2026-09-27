# -*- coding: utf-8 -*-
"""嫌疑句精检：大模型纠错（只改错别字，强约束 JSON 输出）。

主路径：agent-gw chat_completion（复用现有模型，OpenAI 兼容）。
兜底：--no-llm 时用启发式命中的 (错→对) 直接给建议，保证链路可演示。

纠错结果校验（防过度修改）：
  1. "原文"必须在句中真实出现；
  2. 改动字数差 ≤ 1（错别字级，不允许整句改写）；
  3. 不得改动保护词表（定金、不起诉等）。
"""
from __future__ import annotations

import json
import re

from .filters import PROTECTED_TERMS
from .confusion import WRONG2RIGHT

SYSTEM_PROMPT = """你是公文错别字检查器。只检查并修正错别字（同音字、形近字、多字、漏字、叠字）。

严格规则：
1. 只改错别字，不改动标点、不改用词风格、不润色、不重写句子；
2. 专有名词（机构名、人名、法律术语）不得改动；
3. 输出必须是 JSON 数组，每项为 {"原文": "句中连续片段", "改为": "修改后片段", "理由": "一句话"}；
4. "原文"必须是输入句子中逐字存在的连续片段；
5. 如果没有错别字，输出 []；
6. 不要输出 JSON 以外的任何内容。"""


class LLMCorrector:
    def __init__(self, model: str | None = None):
        from agent_gw.client import AgentGwClient
        self.client = AgentGwClient()
        if model is None:
            models = self.client.list_models()
            ids = [m.get("id", "") for m in models.get("data", models if isinstance(models, list) else [])]
            prefer = [i for i in ids if any(k in i.lower() for k in ("k2", "k3", "kimi", "moonshot"))]
            model = (prefer or ids or ["kimi-k2"])[0]
        self.model = model

    def correct(self, sentence: str, suspect_chars=None) -> list[dict]:
        hint = ""
        if suspect_chars:
            chars = "、".join(f"「{c}」" for _, c, _ in suspect_chars[:6])
            hint = f"\n检测器标记的疑似错字位置：{chars}（仅供参考，需自行判断）。"
        resp = self.client.chat_completion(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"请检查这句话：\n{sentence}{hint}"},
            ],
            temperature=0,
        )
        text = resp["choices"][0]["message"]["content"]
        return _parse_and_validate(text, sentence)


class HeuristicCorrector:
    """无 LLM 兜底：直接用混淆词典命中给建议。"""

    def correct(self, sentence: str, suspect_chars=None) -> list[dict]:
        out = []
        for wrong, right in WRONG2RIGHT.items():
            if wrong in sentence:
                out.append({"原文": wrong, "改为": right, "理由": "混淆词表命中"})
        return out


def _parse_and_validate(raw: str, sentence: str) -> list[dict]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    valid = []
    for it in items if isinstance(items, list) else []:
        src, dst = str(it.get("原文", "")), str(it.get("改为", ""))
        if not src or not dst or src == dst:
            continue
        if src not in sentence:
            continue
        if abs(len(dst) - len(src)) > 1:
            continue
        if any(term in src and term not in dst for term in PROTECTED_TERMS):
            continue
        valid.append({"原文": src, "改为": dst, "理由": str(it.get("理由", ""))})
    return valid
