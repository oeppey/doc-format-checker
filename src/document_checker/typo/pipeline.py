# -*- coding: utf-8 -*-
"""错别字检查主链路：解析 → 过滤 → 拆句 → 粗筛 → 精检 → 报告。"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from ..docx_parser import parse_document
from .splitter import split_paragraph
from .filters import should_skip


@dataclass
class TypoFinding:
    para_index: int        # 段落号（1 起，面向用户）
    sent_start: int        # 句内偏移
    sentence: str
    original: str          # 错字片段
    suggestion: str        # 建议改为
    reason: str
    score: float           # 检测器嫌疑分
    source: str            # llm / heuristic

    @property
    def location(self):
        return f"第{self.para_index}段·第{self.sent_start + 1}字"


@dataclass
class TypoReport:
    file: str
    findings: list[TypoFinding] = field(default_factory=list)
    total_sentences: int = 0
    skipped: int = 0
    suspect: int = 0
    detector_name: str = ""
    corrector_name: str = ""
    created_at: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def render_markdown(self) -> str:
        lines = [
            "# 错别字检查报告", "",
            f"- 文件：`{self.file}`",
            f"- 检查时间：{self.created_at}",
            f"- 检测器：{self.detector_name}；精检：{self.corrector_name}",
            f"- 句子：共 {self.total_sentences} 句，过滤 {self.skipped} 句，"
            f"粗筛嫌疑 {self.suspect} 句，确认问题 {len(self.findings)} 处", "",
        ]
        if self.findings:
            lines += [
                "| # | 位置 | 原文 | 建议改为 | 理由 | 嫌疑分 | 所在句 |",
                "|---|---|---|---|---|---|---|",
            ]
            for n, f in enumerate(self.findings, 1):
                sent = f.sentence if len(f.sentence) <= 40 else f.sentence[:40] + "…"
                cells = [str(n), f.location, f.original, f.suggestion, f.reason,
                         f"{f.score:.2f}", sent]
                lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
        else:
            lines.append("未发现错别字。")
        lines.append("")
        return "\n".join(lines)


def run_typo_check(path: str, threshold: float = 0.5, use_llm: bool = True,
                   llm_model: str | None = None, detector_backend=None,
                   corrector_backend=None) -> TypoReport:
    from .detector import get_detector
    from .corrector import LLMCorrector, HeuristicCorrector

    model = parse_document(path)
    sentences = []
    skipped = 0
    for p in model.paragraphs:
        if p.is_blank:
            continue
        for s in split_paragraph(p.index, p.text):
            if should_skip(s.text):
                skipped += 1
            else:
                sentences.append(s)

    detector, det_name = detector_backend or get_detector(threshold=threshold)
    if corrector_backend:
        corrector, cor_name = corrector_backend
    elif use_llm:
        try:
            c = LLMCorrector(llm_model)
            corrector, cor_name = c, f"llm:{c.model}"
        except Exception as e:  # noqa: BLE001
            corrector, cor_name = HeuristicCorrector(), f"heuristic（LLM 不可用：{e}）"
    else:
        corrector, cor_name = HeuristicCorrector(), "heuristic（--no-llm）"

    report = TypoReport(file=path, total_sentences=len(sentences) + skipped,
                        skipped=skipped, detector_name=det_name, corrector_name=cor_name)
    if not sentences:
        return report

    results = detector.detect([s.text for s in sentences])
    for s, res in zip(sentences, results):
        if res is None:
            continue
        report.suspect += 1
        try:
            fixes = corrector.correct(s.text, res.suspect_chars)
        except Exception:  # noqa: BLE001 — 单句失败不拖垮整篇
            fixes = []
        for fix in fixes:
            src, dst = fix["原文"], fix["改为"]
            off = s.text.find(src)
            report.findings.append(TypoFinding(
                para_index=s.para_index + 1,
                sent_start=s.start + (off if off >= 0 else 0),
                sentence=s.text, original=src, suggestion=dst,
                reason=fix.get("理由", ""), score=res.score,
                source=cor_name.split("（")[0]))
    return report
