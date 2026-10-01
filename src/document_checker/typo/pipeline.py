# -*- coding: utf-8 -*-
"""Typo pipeline with explicit coverage, fallback and failure accounting."""
from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field

from ..docx_parser import parse_document
from .splitter import split_paragraph
from .filters import should_skip


@dataclass
class TypoFinding:
    para_index: int
    sent_start: int  # zero-based offset within paragraph
    sentence: str
    original: str
    suggestion: str
    reason: str
    score: float
    source: str

    @property
    def location(self):
        return f"第{self.para_index}段·第{self.sent_start + 1}字"


@dataclass
class TypoReport:
    file: str
    findings: list[TypoFinding] = field(default_factory=list)
    total_sentences: int = 0
    skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    suspect: int = 0
    dict_fallback: int = 0
    punct_filtered: int = 0
    dropped_suggestions: int = 0
    rejected_sentences: int = 0
    dropped_detail: list[dict] = field(default_factory=list)
    failed_sentences: int = 0
    unchecked_parts: list[str] = field(default_factory=list)
    detector_name: str = ""
    corrector_name: str = ""
    created_at: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @property
    def status(self) -> str:
        if self.failed_sentences:
            return "运行失败"
        if self.unchecked_parts or self.skipped or self.total_sentences == 0:
            return "未检查"
        if self.detector_name.startswith("heuristic") or self.corrector_name.startswith("heuristic"):
            return "未检查"
        return "发现问题" if self.findings else "通过"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status
        return data

    def render_markdown(self) -> str:
        lines = [
            "# 错别字检查报告", "",
            f"- 文件：`{self.file}`",
            f"- 检查时间：{self.created_at}",
            f"- 状态：**{self.status}**",
            f"- 检测器：{self.detector_name}；精检：{self.corrector_name}",
            f"- 句子：共 {self.total_sentences} 句，过滤 {self.skipped} 句，"
            f"粗筛嫌疑 {self.suspect} 句（仅标点嫌疑 {self.punct_filtered} 句不进精检），"
            f"确认问题 {len(self.findings)} 处"
            f"（其中词表兜底 {self.dict_fallback} 处），"
            f"低置信建议过滤 {self.dropped_suggestions} 条，"
            f"精检建议被校验拒绝 {self.rejected_sentences} 句，失败 {self.failed_sentences} 句", "",
        ]
        if self.skip_reasons:
            lines.append("- 过滤原因：" + "；".join(f"{k} {v} 句" for k, v in sorted(self.skip_reasons.items())))
        if self.unchecked_parts:
            lines += ["", "## 未检查范围", ""]
            lines += [f"- {part}" for part in self.unchecked_parts]
        if self.findings:
            lines += ["", "## 问题明细", "",
                      "| # | 位置 | 原文 | 建议改为 | 理由 | 嫌疑分 | 所在句 |",
                      "|---|---|---|---|---|---|---|"]
            for n, f in enumerate(self.findings, 1):
                sent = f.sentence if len(f.sentence) <= 40 else f.sentence[:40] + "…"
                cells = [str(n), f.location, f.original, f.suggestion, f.reason,
                         f"{f.score:.2f}", sent]
                lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
        else:
            lines += ["", "## 问题明细", "",
                      "未发现已检查范围内的错别字。" if self.status in ("未检查", "运行失败") else "未发现错别字。"]
        lines.append("")
        return "\n".join(lines)


PUNCT_CHARS = set("，、。；：？！“”‘’（）《》〈〉—…·")


def _covered_by_suspect(off: int, src: str, suspect_chars) -> bool:
    """交叉验证：精检建议的位置须与初筛嫌疑字重叠（ELECTRA 提供字级位置时）。

    实测（docs/corrector_eval.md 第 8 节）：真实文档上 4B 的幻觉建议位置
    大多不在嫌疑范围内；检测器未给字级位置（启发式）时不做此过滤。
    """
    if not suspect_chars:
        return True
    n = max(len(src), 1)
    return any(off < c + len(ch) and c < off + n for c, ch, _ in suspect_chars)


def _locate(sentence, src: str, suspect_chars) -> int | None:
    positions = []
    start = 0
    while (pos := sentence.text.find(src, start)) >= 0:
        positions.append(pos)
        start = pos + 1
    if len(positions) == 1:
        return positions[0]
    hints = [pos for pos, *_ in (suspect_chars or [])]
    matches = [pos for pos in positions if any(pos <= h < pos + len(src) for h in hints)]
    return matches[0] if len(matches) == 1 else None


def run_typo_check(path: str, threshold: float = 0.85, use_llm: bool = True,
                   llm_model: str | None = None, detector_backend=None,
                   corrector_backend=None, model=None, detector_model_dir: str | None = None,
                   detector_device: str = "auto", corrector_base_url: str | None = None,
                   corrector_protocol: str | None = None, require_models: bool = False,
                   use_dict_fallback: bool = True) -> TypoReport:
    from .detector import get_detector
    from .corrector import CorrectionRejected, HeuristicCorrector
    from .confusion import dict_fallback_fixes
    from .service_corrector import OpenAICorrector

    model = model or parse_document(path)
    sentences = []
    reasons: dict[str, int] = {}
    for p in model.paragraphs:
        if p.is_blank:
            continue
        for s in split_paragraph(p.index, p.text):
            reason = should_skip(s.text)
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
            else:
                sentences.append(s)

    detector, det_name = detector_backend or get_detector(
        model_dir=detector_model_dir, threshold=threshold,
        device=detector_device, strict=require_models)
    if corrector_backend:
        corrector, cor_name = corrector_backend
    elif use_llm:
        try:
            c = OpenAICorrector(llm_model, base_url=corrector_base_url,
                                protocol=corrector_protocol)
            corrector, cor_name = c, f"llm:{c.model}"
        except Exception as exc:
            if require_models:
                raise RuntimeError(f"4B／27B 精检不可用：{exc}") from exc
            corrector, cor_name = HeuristicCorrector(), f"heuristic（LLM 不可用：{exc}）"
    else:
        if require_models:
            raise ValueError("严格模型模式不能与 --no-llm 同用")
        corrector, cor_name = HeuristicCorrector(), "heuristic（--no-llm）"

    format_only_notes = set(model.format_only_unchecked_parts)
    report = TypoReport(
        file=path, total_sentences=len(sentences) + sum(reasons.values()),
        skipped=sum(reasons.values()), skip_reasons=reasons,
        detector_name=det_name, corrector_name=cor_name,
        unchecked_parts=[part for part in model.unchecked_parts
                         if part not in format_only_notes],
    )
    if model.footer_paras:
        count = sum(bool(p.text.strip()) for p in model.footer_paras)
        if count:
            report.unchecked_parts.append(f"页脚内 {count} 个非空段落未作错字检查")
    if det_name.startswith("heuristic"):
        report.unchecked_parts.append("ELECTRA 初筛未执行；启发式结果仅供链路验证")
    if cor_name.startswith("heuristic"):
        report.unchecked_parts.append("4B／27B 精检未执行；启发式结果不代表模型验收")
    if not sentences:
        return report

    # 词表兜底：对每句做确定性检查，与模型路径相互独立；记录位置用于模型建议去重
    fallback_spans: set[tuple[int, int, int]] = set()
    if use_dict_fallback:
        for s in sentences:
            for fix in dict_fallback_fixes(s.text):
                off = fix["offset"]
                report.findings.append(TypoFinding(
                    para_index=s.para_index + 1, sent_start=s.start + off,
                    sentence=s.text, original=fix["原文"], suggestion=fix["改为"],
                    reason=fix["理由"], score=1.0, source="词表兜底"))
                fallback_spans.add((s.para_index + 1, s.start + off,
                                    s.start + off + len(fix["原文"])))
        report.dict_fallback = len(fallback_spans)

    try:
        results = detector.detect([s.text for s in sentences])
        if len(results) != len(sentences):
            raise RuntimeError(f"粗筛返回 {len(results)} 项，预期 {len(sentences)} 项")
    except Exception as exc:
        report.failed_sentences = len(sentences)
        report.unchecked_parts.append(f"粗筛失败：{type(exc).__name__}: {exc}")
        return report
    truncated = set(getattr(detector, "last_truncated", []))
    if truncated:
        report.unchecked_parts.append(f"{len(truncated)} 句超过模型长度限制，未作粗筛")
    for index, (s, res) in enumerate(zip(sentences, results)):
        if index in truncated or res is None:
            continue
        report.suspect += 1
        if res.suspect_chars and all(ch in PUNCT_CHARS for _, ch, _ in res.suspect_chars):
            report.punct_filtered += 1
            continue  # 仅标点嫌疑不进精检：错字检查不管标点，且实测这类嫌疑全是噪声
        try:
            fixes = corrector.correct(s.text, res.suspect_chars)
            for fix in fixes:
                src, dst = fix["原文"], fix["改为"]
                off = fix.get("offset")
                if off is None:
                    off = _locate(s, src, res.suspect_chars)
                elif not isinstance(off, int) or off < 0 or s.text[off:off + len(src)] != src:
                    raise ValueError("精检建议的偏移与原句不符")
                if off is None:
                    raise ValueError(f"片段 {src!r} 在句中重复，无法唯一定位")
                abs_start = s.start + off
                if any(fp == s.para_index + 1 and abs_start < fe and fs < abs_start + len(src)
                       for fp, fs, fe in fallback_spans):
                    continue  # 词表兜底已报同一位置，模型建议去重
                if not _covered_by_suspect(off, src, res.suspect_chars):
                    report.dropped_suggestions += 1
                    report.dropped_detail.append({
                        "para_index": s.para_index + 1, "sent_start": abs_start,
                        "original": src, "suggestion": dst,
                        "reason": "建议位置不在初筛嫌疑范围内，按低置信过滤"})
                    continue
                report.findings.append(TypoFinding(
                    para_index=s.para_index + 1, sent_start=s.start + off,
                    sentence=s.text, original=src, suggestion=dst,
                    reason=fix.get("理由", ""), score=res.score, source=cor_name))
        except CorrectionRejected as exc:
            # 模型给了回答但未通过校验：句子已经过初筛与兜底，按低置信留痕，不算失败
            report.rejected_sentences += 1
            report.dropped_detail.append({
                "para_index": s.para_index + 1, "sent_start": s.start,
                "original": "", "suggestion": "",
                "reason": f"精检建议未通过校验：{exc}"})
        except Exception as exc:
            report.failed_sentences += 1
            report.unchecked_parts.append(
                f"第{s.para_index + 1}段第{s.start + 1}字起精检失败：{type(exc).__name__}: {exc}"
            )
    return report
