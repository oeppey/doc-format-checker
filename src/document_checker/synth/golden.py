# -*- coding: utf-8 -*-
"""Golden Document 生成：从规则 YAML 推导生成参数（单一事实源）。

规则 YAML 是唯一需要维护的地方——例如标题字号从"小一"改成"二号"，
只改 src/document_checker/rules/呈报稿-大字版.yaml 里的 size_pt，重新生成语料即可，
生成器参数不需要任何手工同步。
"""
from __future__ import annotations

import copy

from ..rule_engine import RuleEngine
from .sample_gen import BASE_CONFIG

_TYPE_ALIAS = {"dazi": "chengbaogao_dazi", "xiaozi": "chengbaogao_xiaozi"}


def resolve_doc_type(doc_type: str) -> str:
    return _TYPE_ALIAS.get(doc_type, doc_type)


def build_cfg(rules_dir: str, doc_type: str) -> dict:
    """从规则集推导生成配置；规则里没写的项（如三级标题字体）回落到基准默认。"""
    doc_type = resolve_doc_type(doc_type)
    engine = RuleEngine(rules_dir)
    rs = engine.rulesets[doc_type]
    merged = engine._merged_rules(rs)

    base_key = "dazi" if "dazi" in doc_type else "xiaozi"
    cfg = copy.deepcopy(BASE_CONFIG[base_key])
    cfg["doc_type"] = doc_type

    for r in merged:
        p = r.get("params", {}) or {}
        rid = r["id"]
        if rid == "page-setup":
            cfg["margins"] = {"top": p["top_cm"], "bottom": p["bottom_cm"],
                              "left": p["left_cm"], "right": p["right_cm"]}
        elif rid == "font-title":
            cfg["title"] = {"font": p["fonts"][0], "size": p["size_pt"],
                            "bold": p.get("bold", False)}
        elif rid == "font-body":
            cfg["body"] = {"font": p["fonts"][0], "size": p["size_pt"],
                           "bold": p.get("bold", False)}
        elif rid == "font-heading-1":
            cfg["h1"] = {"font": p["fonts"][0], "size": p["size_pt"],
                         "bold": p.get("bold", False)}
        elif rid == "font-heading-2":
            cfg["h2"] = {"font": p["fonts"][0], "size": p["size_pt"],
                         "bold": p.get("bold", False)}
        elif rid == "line-spacing":
            cfg["line_pt"] = p["line_pt"]
        elif rid == "char-spacing":
            cfg["char_spacing_pt"] = p.get("spacing_pt", 0.0)
        elif rid == "secrecy-format":
            cfg["secrecy"].update({"font": p["fonts"][0], "size": p["size_pt"],
                                   "bold": p.get("bold", True)})
        elif rid == "page-number":
            cfg["page_num"].update({"dash": p.get("dash", "—"),
                                    "font": p["fonts"][0], "size": p["size_pt"]})
            cfg["footer_distance"] = p.get("footer_distance_cm", cfg["footer_distance"])
    # 三级标题未单独立规，随正文
    cfg["h3"] = copy.deepcopy(cfg["body"])
    return cfg
