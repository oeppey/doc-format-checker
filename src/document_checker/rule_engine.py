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
from .rules_schema import validate_ruleset, InvalidRuleError


class RuleEngine:
    def __init__(self, rules_dir: str):
        self.rules_dir = rules_dir
        self.rulesets: dict[str, dict] = {}
        self.common: dict | None = None
        for f in sorted(glob.glob(os.path.join(rules_dir, "*.yaml"))):
            with open(f, encoding="utf-8") as fp:
                data = yaml.safe_load(fp)
            validate_ruleset(data, f)
            rule_set_id = data["meta"]["id"]
            if rule_set_id == "common":
                if self.common is not None:
                    raise InvalidRuleError(f"{f}: 重复 common 规则集")
                self.common = data
            else:
                if rule_set_id in self.rulesets:
                    raise InvalidRuleError(f"{f}: 重复规则集 ID：{rule_set_id}")
                self.rulesets[rule_set_id] = data
        if not self.rulesets:
            raise RuntimeError(f"规则目录 {rules_dir} 下没有找到规则集")
        for rule_set_id, ruleset in self.rulesets.items():
            validate_ruleset({"meta": {"id": rule_set_id},
                              "rules": self._merged_rules(ruleset)},
                             f"{rules_dir}/{rule_set_id}（合并后）")

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

    def check(self, path: str, doc_type: str | None = None, model=None) -> Report:
        model = model or parse_document(path)
        roles, para_role = map_roles(model)
        if doc_type is None:
            doc_type = self.detect_type(model, roles)
            if doc_type is None:
                raise ValueError("无法判定文书类型；请用 --type 明确指定 dazi 或 xiaozi")
        if doc_type not in self.rulesets:
            raise KeyError(f"未知文书类型：{doc_type}，可选：{list(self.rulesets)}")
        rs = self.rulesets[doc_type]

        return self._run_rules(model, roles, rs)

    def check_custom(self, path: str, ruleset: dict, model=None) -> Report:
        validate_ruleset(ruleset, "custom-template")
        model = model or parse_document(path)
        roles, _ = map_roles(model)
        return self._run_rules(model, roles, ruleset, custom=True)

    def _run_rules(self, model, roles, rs: dict, *, custom: bool = False) -> Report:
        doc_type = rs["meta"]["id"]
        findings, rule_results = [], []
        for r in (rs['rules'] if custom else self._merged_rules(rs)):
            fn = CHECKERS[r["checker"]]  # YAML 已在加载时校验
            params = r.get("params", {}) or {}
            target_role = params.get("role")
            target_roles = params.get("roles")
            if target_role and not roles.get(target_role) and not params.get("required"):
                rule_results.append(RuleResult(r["id"], r.get("name", r["id"]), "不适用", 0,
                                               f"文档中未识别到 {target_role} 段落"))
                continue
            if target_roles and not any(roles.get(role) for role in target_roles):
                rule_results.append(RuleResult(r["id"], r.get("name", r["id"]), "不适用", 0,
                                               "未识别到适用段落"))
                continue
            try:
                fs = fn(model, roles, params)
            except Exception as exc:  # 单条规则失败需进入报告，不能伪装为通过
                rule_results.append(RuleResult(r["id"], r.get("name", r["id"]),
                                               "运行失败", 0, f"{type(exc).__name__}: {exc}"))
                continue
            for f in fs:
                f.rule_id = r["id"]
                f.rule_name = r.get("name", r["id"])
                f.severity = f.severity or r.get("severity", "error")
            findings.extend(fs)
            rule_results.append(RuleResult(
                rule_id=r["id"], name=r.get("name", r["id"]),
                status="通过" if not fs else "发现问题", count=len(fs)))

        return Report(file=model.path, doc_type=doc_type,
                      ruleset_name=rs["meta"].get("name", doc_type),
                      rule_results=rule_results, findings=findings,
                      roles={k: v for k, v in roles.items()},
                      unchecked_parts=getattr(model, "unchecked_parts", []))
