"""OpenAI-compatible correction service adapter."""
from __future__ import annotations

import difflib
import os
import re

from .corrector import SYSTEM_PROMPT, _edit_distance, _parse_and_validate, validate_corrections

CORRECTED_TEXT_PROMPT = (
    "只纠正下句中的错别字，保持其他文字、标点和空白不变。"
    "只输出纠正后的完整句子；如果没有错别字，原样输出。"
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def corrected_text_to_fixes(raw: str, sentence: str) -> list[dict]:
    if "<think>" in raw.lower() and not _THINK_RE.search(raw):
        raise ValueError("4B 输出的思考段未闭合")
    corrected = _THINK_RE.sub("", raw).strip()
    if not corrected:
        raise ValueError("精检模型未返回纠正后的句子")
    if corrected == sentence:
        return []
    items = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, sentence, corrected, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        src, dst = sentence[i1:i2], corrected[j1:j2]
        if len(src) > 2 or len(dst) > 2 or _edit_distance(src, dst) > 1:
            raise ValueError("模型改写幅度超过单处错别字范围")
        items.append({"原文": src, "改为": dst, "理由": "模型建议", "offset": i1})
    if len(items) > 3:
        raise ValueError("模型对单句提出过多修改，需人工复核")
    return validate_corrections(items, sentence)


class OpenAICorrector:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 protocol: str | None = None, client=None):
        self.model = model or os.environ.get("DOCUMENT_CHECKER_CORRECTOR_MODEL")
        if not self.model:
            raise ValueError("未指定精检模型；请设置 --model 或 DOCUMENT_CHECKER_CORRECTOR_MODEL")
        self.base_url = (base_url or os.environ.get("DOCUMENT_CHECKER_CORRECTOR_BASE_URL") or "").rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("未指定有效精检服务地址；请设置 DOCUMENT_CHECKER_CORRECTOR_BASE_URL（含 /v1）")
        self.protocol = protocol or os.environ.get("DOCUMENT_CHECKER_CORRECTOR_PROTOCOL")
        if self.protocol is None:
            self.protocol = "corrected_text" if "ChineseErrorCorrector4-4B" in self.model else "json"
        if self.protocol not in {"corrected_text", "json"}:
            raise ValueError("精检返回协议必须是 corrected_text 或 json")
        timeout = float(os.environ.get("DOCUMENT_CHECKER_CORRECTOR_TIMEOUT_S", "60"))
        if timeout <= 0:
            raise ValueError("精检超时必须大于零")
        import httpx
        self.client = client or httpx.Client(timeout=timeout)

    def correct(self, sentence: str, suspect_chars=None) -> list[dict]:
        hint = ""
        if suspect_chars:
            chars = "、".join(f"「{c}」" for _, c, _ in suspect_chars[:6])
            if self.protocol == "json":
                hint = f"\n检测器标记的疑似错字位置：{chars}（仅供参考）。"
            else:
                hint = f"\n检测器标记的疑似错字：{chars}（仅供参考，请重点核对）。"
        if self.protocol == "corrected_text":
            user_content = f"{sentence}{hint}"
        else:
            user_content = f"请检查这句话：\n{sentence}{hint}"
        messages = [
            {"role": "system", "content": CORRECTED_TEXT_PROMPT if self.protocol == "corrected_text" else SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        headers = {}
        api_key = os.environ.get("DOCUMENT_CHECKER_CORRECTOR_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = self.client.post(
            f"{self.base_url}/chat/completions",
            json={"model": self.model, "messages": messages, "temperature": 0, "max_tokens": 512},
            headers=headers,
        )
        resp.raise_for_status()
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ValueError("精检服务返回结构无效") from exc
        if not isinstance(content, str):
            raise ValueError("精检服务没有返回文本")
        if self.protocol == "corrected_text":
            return corrected_text_to_fixes(content, sentence)
        return _parse_and_validate(content, sentence)
