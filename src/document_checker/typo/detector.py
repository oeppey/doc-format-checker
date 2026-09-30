# -*- coding: utf-8 -*-
"""Adapters for sentence-level typo suspicion."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .confusion import WRONG2RIGHT


def _default_model_dir() -> str:
    if os.environ.get("CED_MODEL_DIR"):
        return os.environ["CED_MODEL_DIR"]
    for directory in ("/tmp/models/ChineseErrorDetectorElectra",
                      "/mnt/agents/models/ChineseErrorDetectorElectra"):
        if os.path.isfile(os.path.join(directory, "model.safetensors")):
            return directory
    return "/tmp/models/ChineseErrorDetectorElectra"


DEFAULT_MODEL_DIR = _default_model_dir()


@dataclass
class SuspectResult:
    score: float
    suspect_chars: list[tuple[int, str, float]] = field(default_factory=list)
    hits: list[tuple[str, str]] = field(default_factory=list)


def error_label_index(id2label: dict) -> int:
    matches = [
        int(index) for index, label in id2label.items()
        if str(label).strip().lower() in {"err", "error", "typo", "incorrect", "错", "错误"}
    ]
    if len(matches) != 1:
        raise ValueError(f"ELECTRA 错误标签无法唯一确定：{id2label}")
    return matches[0]


class ElectraDetector:
    def __init__(self, model_dir: str = DEFAULT_MODEL_DIR, threshold: float = 0.85,
                 device: str = "auto", batch_size: int = 32, max_tokens: int = 512):
        if not 0 <= threshold <= 1 or batch_size < 1 or max_tokens < 1:
            raise ValueError("阈值、批量大小或 token 上限无效")
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer
        self.torch = torch
        self.threshold = threshold
        self.batch_size = batch_size
        self.max_tokens = max_tokens
        self.device = "cuda" if device == "auto" and torch.cuda.is_available() else ("cpu" if device == "auto" else device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
        if not self.tokenizer.is_fast:
            raise ValueError("ELECTRA 需要 fast tokenizer 才能可靠返回字符偏移")
        self.model = AutoModelForTokenClassification.from_pretrained(model_dir)
        self.error_index = error_label_index(self.model.config.id2label)
        self.model.to(self.device)
        self.model.eval()
        self.last_truncated: list[int] = []

    def detect(self, sentences: list[str]) -> list[SuspectResult | None]:
        self.last_truncated = []
        output: list[SuspectResult | None] = [None] * len(sentences)
        valid = []
        for index, sentence in enumerate(sentences):
            length = len(self.tokenizer(sentence, add_special_tokens=True)["input_ids"])
            if length > self.max_tokens:
                self.last_truncated.append(index)
            else:
                valid.append(index)
        for start in range(0, len(valid), self.batch_size):
            indices = valid[start:start + self.batch_size]
            batch = [sentences[index] for index in indices]
            enc = self.tokenizer(
                batch, return_tensors="pt", padding=True, truncation=False,
                return_offsets_mapping=True,
            )
            offsets = enc.pop("offset_mapping").tolist()
            masks = enc["attention_mask"].tolist()
            model_inputs = {key: value.to(self.device) for key, value in enc.items()}
            with self.torch.no_grad():
                logits = self.model(**model_inputs).logits
            probs = self.torch.softmax(logits, dim=-1)[..., self.error_index].cpu()
            for row, index in enumerate(indices):
                hits = []
                for token, (first, last) in enumerate(offsets[row]):
                    if not masks[row][token] or first == last:
                        continue
                    score = float(probs[row][token])
                    if score >= self.threshold:
                        hits.append((first, sentences[index][first:last], round(score, 3)))
                if hits:
                    output[index] = SuspectResult(
                        score=max(score for _, _, score in hits), suspect_chars=hits,
                    )
        return output


class HeuristicDetector:
    """Small confusion dictionary for route verification, not model evaluation."""

    DUP_ALLOW = set("刚天个渐常仅每各多渐步条层")

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    def detect(self, sentences: list[str]) -> list[SuspectResult | None]:
        output = []
        for sentence in sentences:
            hits = [(wrong, right) for wrong, right in WRONG2RIGHT.items() if wrong in sentence]
            chars = []
            for match in re.finditer(r"(.)\1", sentence):
                if match.group(1) not in self.DUP_ALLOW and match.group(1) not in "，。、；：":
                    chars.append((match.start(), match.group(1), 0.6))
            if hits or chars:
                output.append(SuspectResult(
                    score=max([0.9] * len(hits) + [score for _, _, score in chars]),
                    suspect_chars=chars, hits=hits,
                ))
            else:
                output.append(None)
        return output


def get_detector(prefer: str = "electra", model_dir: str | None = None,
                 threshold: float = 0.85, device: str = "auto", strict: bool = False):
    model_dir = model_dir or _default_model_dir()
    if prefer == "heuristic":
        if strict:
            raise ValueError("严格模型模式不允许启发式检测器")
        return HeuristicDetector(threshold), "heuristic（手动指定）"
    try:
        return ElectraDetector(model_dir, threshold, device=device), f"electra @ {model_dir} ({device})"
    except Exception as exc:
        if strict:
            raise RuntimeError(f"ELECTRA 初筛不可用：{exc}") from exc
        return HeuristicDetector(threshold), f"heuristic（ELECTRA 不可用：{exc}）"
