# -*- coding: utf-8 -*-
"""规则引擎：加载 YAML 规则集 → 解析文档 → 角色映射 → 调度检查器 → 汇总报告。

规则集支持两层：common.yaml（通用注意事项）+ 具体文书类型（按规则 id 覆盖合并），
需求迭代时原则上只改 YAML，不动代码。
"""
from __future__ import annotations

import copy
import glob
import os

import yaml

from .checkers import CHECKERS
from .docx_parser import parse_document
from .role_mapper import map_roles
from .report import Report, RuleResult


class RuleEngine:
    def __init__(self, rules_dir: str):
        self.rules_dir = rules_dir
        self.rulesets: dict[str, dict] = {}
        self.common: dict | None = None
        for f in sorted(glob.glob(os.path.join(rules_dir, "*.yaml"))):
            with open(f, encoding="utf-8") as fp:
                data = yaml.safe_load(fp)
            if data["meta"].get("id") == "common":
                self.common = data
            else:
                self.rulesets[data["meta"]["id"]] = data
        if not self.rulesets:
            raise RuntimeError(f"规则目录 {rules_dir} 下没有找到规则集")

    def _merged_rules(self, rs: dict) -> list[dict]:
        merged: dict[str, dict] = {}
        if self.common:
            for r in self.common.get("rules", []):
                merged[r["id"]] = copy.deepcopy(r)
        for r in rs.get("rules", []):
            if r["id"] in merged:
                base = merged[r["id"]]
                base.update({k: v for k, v in r.items() if k != "params"})
                base.setdefault("params", {}).update(r.get("params", {}))
            else:
                merged[r["id"]] = copy.deepcopy(r)
        return list(merged.values())

    def detect_type(self, model, roles) -> str | None:
        """按标题字号自动识别文书类型（小一 24pt → 大字版，二号 22pt → 小字版）。"""
        t = roles.get("title")
        if not t:
            return None
        size = model.paragraphs[t[0]].main_size()
        if size is None:
            return None
        for rid, rs in self.rulesets.items():
            for r in rs.get("rules", []):
                if r.get("checker") == "font_format" and r.get("params", {}).get("role") == "title":
                    if abs(size - r["params"]["size_pt"]) < 0.5:
                        return rid
        return None

    def check(self, path: str, doc_type: str | None = None) -> Report:
        model = parse_document(path)
        roles, para_role = map_roles(model)
        if doc_type is None:
            doc_type = self.detect_type(model, roles) or next(iter(self.rulesets))
        if doc_type not in self.rulesets:
            raise KeyError(f"未知文书类型：{doc_type}，可选：{list(self.rulesets)}")
        rs = self.rulesets[doc_type]

        findings, rule_results = [], []
        for r in self._merged_rules(rs):
            fn = CHECKERS.get(r.get("checker"))
            if fn is None:
                rule_results.append(RuleResult(rule_id=r["id"], name=r.get("name", r["id"]),
                                               status="未实现", count=0))
                continue
            fs = fn(model, roles, r.get("params", {}) or {})
            for f in fs:
                f.rule_id = r["id"]
                f.rule_name = r.get("name", r["id"])
                f.severity = f.severity or r.get("severity", "error")
            findings.extend(fs)
            rule_results.append(RuleResult(
                rule_id=r["id"], name=r.get("name", r["id"]),
                status="通过" if not fs else "发现问题", count=len(fs)))
        return Report(file=path, doc_type=doc_type,
                      ruleset_name=rs["meta"].get("name", doc_type),
                      rule_results=rule_results, findings=findings,
                      roles={k: v for k, v in roles.items()})
