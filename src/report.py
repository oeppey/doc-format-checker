# -*- coding: utf-8 -*-
"""检查报告：Markdown / JSON 双形态。"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field, asdict

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
SEVERITY_LABEL = {"error": "错误", "warning": "警告", "info": "提示"}


@dataclass
class RuleResult:
    rule_id: str
    name: str
    status: str   # 通过 / 发现问题 / 未实现
    count: int


@dataclass
class Report:
    file: str
    doc_type: str
    ruleset_name: str
    rule_results: list[RuleResult] = field(default_factory=list)
    findings: list = field(default_factory=list)
    roles: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def counts(self):
        c = {"error": 0, "warning": 0, "info": 0}
        for f in self.findings:
            c[f.severity if f.severity in c else "error"] += 1
        return c

    def to_dict(self):
        d = asdict(self)
        d["counts"] = self.counts()
        return d

    def render_markdown(self) -> str:
        counts = self.counts()
        passed = sum(1 for r in self.rule_results if r.status == "通过")
        lines = [
            "# 公文格式检查报告",
            "",
            f"- 文件：`{self.file}`",
            f"- 适用规则集：{self.ruleset_name}（`{self.doc_type}`）",
            f"- 检查时间：{self.created_at}",
            f"- 规则执行：共 {len(self.rule_results)} 条，通过 {passed} 条",
            f"- 问题统计：错误 {counts['error']} ｜ 警告 {counts['warning']} ｜ 提示 {counts['info']}",
            "",
        ]
        if self.findings:
            lines += [
                "## 问题明细", "",
                "| # | 规则 | 级别 | 位置 | 问题 | 期望值 | 实际值 | 修复建议 |",
                "|---|---|---|---|---|---|---|---|",
            ]
            ordered = sorted(self.findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
            for n, f in enumerate(ordered, 1):
                cells = [str(n), f.rule_name, SEVERITY_LABEL.get(f.severity, f.severity),
                         f.location, f.message, f.expected, f.actual, f.suggestion]
                lines.append("| " + " | ".join(_esc(c) for c in cells) + " |")
            lines.append("")
        else:
            lines += ["## 问题明细", "", "未发现问题。", ""]
        lines += ["## 规则执行概览", "", "| 规则ID | 名称 | 结果 | 问题数 |", "|---|---|---|---|"]
        for r in self.rule_results:
            lines.append(f"| {r.rule_id} | {r.name} | {r.status} | {r.count} |")
        lines.append("")
        return "\n".join(lines)


def _esc(s) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")
