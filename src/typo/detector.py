# -*- coding: utf-8 -*-
"""嫌疑句检测（粗筛）。

主路径：ChineseErrorDetectorElectra（字级 token 分类，输出每个字为错别字的概率）。
兜底：混淆词典 + 叠字规则的启发式检测器（模型不可用时保证链路能跑通）。

统一接口 detect(list[str]) -> list[SuspectResult|None]
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .confusion import WRONG2RIGHT

def _default_model_dir() -> str:
    """候选路径：环境变量 > /tmp（会话内）> /mnt/agents（受 100MB 单文件限制可能不完整）。"""
    if os.environ.get("CED_MODEL_DIR"):
        return os.environ["CED_MODEL_DIR"]
    for d in ("/tmp/models/ChineseErrorDetectorElectra",
              "/mnt/agents/models/ChineseErrorDetectorElectra"):
        if os.path.isfile(os.path.join(d, "model.safetensors")):
            return d
    return "/tmp/models/ChineseErrorDetectorElectra"


DEFAULT_MODEL_DIR = _default_model_dir()


@dataclass
class SuspectResult:
    score: float                      # 句级嫌疑分（字级最大概率）
    suspect_chars: list[tuple[int, str, float]] = field(default_factory=list)  # (位置, 字, 概率)
    hits: list[tuple[str, str]] = field(default_factory=list)  # 启发式命中 (错, 对)


class ElectraDetector:
    def __init__(self, model_dir: str = DEFAULT_MODEL_DIR, threshold: float = 0.5):
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer
        self.torch = torch
        self.threshold = threshold
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForTokenClassification.from_pretrained(model_dir)
        self.model.eval()

    def detect(self, sentences: list[str]) -> list[SuspectResult | None]:
        if not sentences:
            return []
        torch = self.torch
        enc = self.tokenizer(
            sentences, return_tensors="pt", padding=True, truncation=True,
            max_length=512, return_offsets_mapping=True)
        with torch.no_grad():
            logits = self.model(input_ids=enc["input_ids"],
                                attention_mask=enc["attention_mask"]).logits
        probs = torch.softmax(logits, dim=-1)[..., 1]  # label 1 = ERR
        offsets = enc["offset_mapping"].tolist()
        masks = enc["attention_mask"].tolist()
        results = []
        for si, sent in enumerate(sentences):
            char_hits = []
            for ti, (s, e) in enumerate(offsets[si]):
                if not masks[si][ti] or s == e:
                    continue
                p = float(probs[si][ti])
                if p >= self.threshold:
                    char_hits.append((s, sent[s:e], round(p, 3)))
            if char_hits:
                results.append(SuspectResult(
                    score=max(p for _, _, p in char_hits), suspect_chars=char_hits))
            else:
                results.append(None)
        return results


class HeuristicDetector:
    """兜底：查混淆词典 + 叠字。"""

    DUP_ALLOW = set("刚天个渐常仅每各多渐步条层")  # 合法叠字常用首字（粗粒度）

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    def detect(self, sentences: list[str]) -> list[SuspectResult | None]:
        out = []
        for sent in sentences:
            hits = [(w, r) for w, r in WRONG2RIGHT.items() if w in sent]
            chars = []
            for m in re.finditer(r"(.)\1", sent):
                if m.group(1) not in self.DUP_ALLOW and m.group(1) not in "，。、；：":
                    chars.append((m.start(), m.group(1), 0.6))
            if hits or chars:
                out.append(SuspectResult(
                    score=max([0.9] * len(hits) + [p for _, _, p in chars]),
                    suspect_chars=chars, hits=hits))
            else:
                out.append(None)
        return out


def get_detector(prefer: str = "electra", model_dir: str = DEFAULT_MODEL_DIR,
                 threshold: float = 0.5):
    """优先 ELECTRA；模型文件缺失或加载失败时退回启发式，并说明原因。"""
    if prefer == "heuristic":
        return HeuristicDetector(threshold), "heuristic（手动指定）"
    try:
        return ElectraDetector(model_dir, threshold), f"electra @ {model_dir}"
    except Exception as e:  # noqa: BLE001
        return HeuristicDetector(threshold), f"heuristic（ELECTRA 不可用：{e}）"
