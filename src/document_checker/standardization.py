"""Versioned user-facing rule catalog and compiler for currently executable checks."""
from __future__ import annotations

from copy import deepcopy
from math import isfinite

from .docx_parser import CN_FONT_SIZE
from .rules_schema import InvalidRuleError, ROLES, validate_ruleset

# Catalog entries describe product fields. Unsupported visual items cannot be enabled.
_ROWS = [
    ("page.size", "页面设置", "纸张规格", "size", "unavailable"),
    ("page.margin_top", "页面设置", "上边距", "length", "supported"),
    ("page.margin_bottom", "页面设置", "下边距", "length", "supported"),
    ("page.margin_left", "页面设置", "左边距", "length", "supported"),
    ("page.margin_right", "页面设置", "右边距", "length", "supported"),
    ("page.footer_distance", "页面设置", "页脚距纸张底边", "length", "supported"),
    ("font.cjk", "字体与字号", "中文字体", "font", "supported"),
    ("font.latin", "字体与字号", "西文字体", "font", "supported"),
    ("font.size", "字体与字号", "字号", "font_size", "supported"),
    ("font.bold", "字体与字号", "加粗", "bool", "supported"),
    ("font.character_spacing", "字体与字号", "字符间距", "signed_pt", "partial"),
    ("paragraph.alignment", "段落格式", "对齐方式", "alignment", "partial"),
    ("paragraph.line_spacing", "段落格式", "行距", "line_spacing", "partial"),
    ("paragraph.first_line_indent", "段落格式", "首行缩进", "indent", "unavailable"),
    ("paragraph.space_before", "段落格式", "段前间距", "space", "unavailable"),
    ("paragraph.space_after", "段落格式", "段后间距", "space", "unavailable"),
    ("paragraph.latin_wrap", "段落格式", "西文换行", "wrap", "unavailable"),
    ("page_number.field", "页码与版式", "自动页码域", "field", "supported"),
    ("page_number.decoration", "页码与版式", "页码装饰与空格", "decoration", "partial"),
    ("page_number.alignment", "页码与版式", "页码左右位置", "alignment", "partial"),
    ("page_number.font_cjk", "页码与版式", "页码字体", "font", "supported"),
    ("page_number.font_size", "页码与版式", "页码字号", "font_size", "supported"),
    ("page_number.vertical_alignment", "页码与版式", "页码上下位置", "alignment", "unavailable"),
    ("page_number.different_odd_even", "页码与版式", "奇偶页不同", "bool", "supported"),
    ("page_number.odd_padding", "页码与版式", "奇数页页码留空", "padding", "needs_render"),
    ("page_number.even_padding", "页码与版式", "偶数页页码留空", "padding", "needs_render"),
    ("page_number.continuous_on_attachment", "页码与版式", "附件连续编页码", "bool", "unavailable"),
    ("structural.secrecy_position", "其他规范要求", "密级位置", "position", "partial"),
    ("structural.secrecy_inner_space", "其他规范要求", "密级字间空格", "bool", "partial"),
    ("structural.heading_numbering", "其他规范要求", "标题序号", "heading", "partial"),
    ("structural.attachment_indent", "其他规范要求", "附件左空字数", "indent", "partial"),
    ("structural.attachment_blank_before", "其他规范要求", "附件前空段数", "blank", "partial"),
    ("structural.attachment_trailing_punct", "其他规范要求", "附件名称末尾标点", "bool", "partial"),
    ("structural.signature_blank_before", "其他规范要求", "署名前空段数", "blank", "partial"),
    ("structural.date_format", "其他规范要求", "成文日期格式", "date", "partial"),
    ("structural.seal_layout", "印章专项", "印章位置", "seal", "unavailable"),
]
CATALOG = [
    {"id": rid, "group": group, "label": label, "kind": kind, "capability": capability}
    for rid, group, label, kind, capability in _ROWS
]
BY_ID = {item["id"]: item for item in CATALOG}
VERSION = "1.1"
ROLE_IDS = {"font.cjk", "font.latin", "font.size", "font.bold",
            "font.character_spacing", "paragraph.alignment", "paragraph.line_spacing",
            "paragraph.first_line_indent", "paragraph.space_before",
            "paragraph.space_after", "paragraph.latin_wrap"}
PAGE_NUMBER_IDS = {item["id"] for item in CATALOG if item["id"].startswith("page_number.")}


def _number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise InvalidRuleError(f"{label}必须是有限数字")
    return float(value)


def normalize_rule(raw: dict) -> dict:
    if not isinstance(raw, dict) or raw.get("id") not in BY_ID:
        raise InvalidRuleError(f"未知检测项：{getattr(raw, 'get', lambda *_: None)('id')}")
    rid = raw["id"]
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise InvalidRuleError(f"{rid}.enabled 必须为布尔值")
    if enabled and (BY_ID[rid]["capability"] in {"unavailable", "needs_render"} or rid.startswith("structural.") or rid == "page_number.decoration"):
        raise InvalidRuleError(f"{rid} 尚不能自动检查，不能启用")
    scope = deepcopy(raw.get("scope") or {})
    if not isinstance(scope, dict):
        raise InvalidRuleError(f"{rid}.scope 必须是对象")
    if rid in ROLE_IDS:
        role = scope.get("role")
        if role not in ROLES:
            raise InvalidRuleError(f"{rid} 必须指定已知段落角色")
        if scope.get("part", "body") != "body":
            raise InvalidRuleError(f"{rid} 当前只支持正文段落")
        scope = {"part": "body", "role": role}
    elif rid in PAGE_NUMBER_IDS:
        if scope.get("part", "footer-all") != "footer-all":
            raise InvalidRuleError(f"{rid} 当前只能对所有有效页脚统一检查")
        scope = {"part": "footer-all"}
    else:
        scope = {"part": "body"} if rid.startswith("structural.") else {}
    expected = deepcopy(raw.get("expected"))
    if not isinstance(expected, dict):
        raise InvalidRuleError(f"{rid}.expected 必须是对象")
    kind = BY_ID[rid]["kind"]
    if kind == "length":
        value = _number(expected.get("value"), rid)
        unit = expected.get("unit")
        if unit == "mm":
            value /= 10
        elif unit != "cm":
            raise InvalidRuleError(f"{rid} 单位必须为 cm 或 mm")
        if value <= 0:
            raise InvalidRuleError(f"{rid} 必须大于 0")
        expected = {"value": round(value, 3), "unit": "cm"}
    elif kind == "font_size":
        value = expected.get("value")
        if isinstance(value, str) and value in CN_FONT_SIZE:
            value = CN_FONT_SIZE[value]
        else:
            value = _number(value, rid)
            if expected.get("unit") != "pt":
                raise InvalidRuleError(f"{rid} 单位必须为 pt，或输入字号名称")
        if value <= 0:
            raise InvalidRuleError(f"{rid} 必须大于 0")
        expected = {"value": value, "unit": "pt"}
    elif kind == "line_spacing":
        mode = expected.get("mode")
        if mode == "exact":
            value = _number(expected.get("value"), rid)
            unit = expected.get("unit")
            if unit == "cm":
                value *= 72 / 2.54
            elif unit != "pt":
                raise InvalidRuleError(f"{rid} 固定行距单位必须为 pt 或 cm")
            if value <= 0:
                raise InvalidRuleError(f"{rid} 必须大于 0")
            expected = {"mode": "exact", "value": round(value, 2), "unit": "pt"}
        elif enabled:
            raise InvalidRuleError(f"{rid} 目前仅能检查固定行距；倍数及最小值请暂不启用")
    elif kind == "signed_pt":
        value = _number(expected.get("value"), rid)
        if expected.get("unit") != "pt":
            raise InvalidRuleError(f"{rid} 单位必须为 pt")
        if enabled and value < 0:
            raise InvalidRuleError(f"{rid} 紧缩字符间距目前不能启用")
        expected = {"value": value, "unit": "pt"}
    elif kind == "alignment" and enabled:
        allowed = {"left", "center", "right"}
        if rid == "page_number.alignment":
            allowed = {"center"}
        if expected.get("value") not in allowed:
            raise InvalidRuleError(f"{rid} 当前支持的选项：{sorted(allowed)}")
    elif kind == "font":
        if not isinstance(expected.get("value"), str) or not expected["value"].strip():
            raise InvalidRuleError(f"{rid} 字体名称不能为空")
        aliases = expected.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(a, str) or not a.strip() for a in aliases):
            raise InvalidRuleError(f"{rid}.aliases 必须是字体名称列表")
        expected = {"value": expected["value"].strip(), "aliases": aliases}
    elif kind == "padding":
        direction = expected.get("direction")
        value = expected.get("value")
        if direction not in {"left", "right", "none"}:
            raise InvalidRuleError(f"{rid} 方向必须为 left、right 或 none")
        if expected.get("unit") != "char":
            raise InvalidRuleError(f"{rid} 单位必须为 char")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 10:
            raise InvalidRuleError(f"{rid} 字数必须为 0–10 的整数")
        if (direction == "none" and value != 0) or (direction != "none" and value == 0):
            raise InvalidRuleError(f"{rid} 不空时字数必须为 0，其余方向必须至少 1 字")
        expected = {"direction": direction, "value": value, "unit": "char"}
    elif kind == "bool":
        if not isinstance(expected.get("value"), bool):
            raise InvalidRuleError(f"{rid} 必须选择是或否")
        expected = {"value": expected["value"]}
    elif rid == "page_number.field" and enabled and expected.get("value") != "PAGE":
        raise InvalidRuleError("当前仅支持自动 PAGE 域")
    elif rid == "structural.date_format" and enabled and expected.get("value") != "chinese_full":
        raise InvalidRuleError("当前仅支持 YYYY年M月D日")
    elif kind == "blank" and enabled:
        value = expected.get("value")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise InvalidRuleError(f"{rid} 必须为非负整数空段数")
        if expected.get("unit") != "blank_line":
            raise InvalidRuleError(f"{rid} 单位必须为 blank_line")
    elif rid == "structural.heading_numbering" and enabled:
        if expected.get("value") != "standard_four_levels":
            raise InvalidRuleError("目前仅支持一、／（一）／1.／（1）")
    severity = raw.get("severity", "error")
    if severity not in {"error", "warning", "info"}:
        raise InvalidRuleError(f"{rid}.severity 无效")
    required = raw.get("required", False)
    if not isinstance(required, bool):
        raise InvalidRuleError(f"{rid}.required 必须为布尔值")
    if required and rid not in {"font.cjk", "font.latin", "font.size", "font.bold",
                                "paragraph.alignment", "structural.secrecy_inner_space"}:
        raise InvalidRuleError(f"{rid} 目前不支持缺失角色时报告错误")
    tolerance = deepcopy(raw.get("tolerance"))
    if tolerance is not None:
        if not isinstance(tolerance, dict) or "value" not in tolerance:
            raise InvalidRuleError(f"{rid}.tolerance 格式错误")
        tol = _number(tolerance["value"], rid + ".tolerance")
        unit = tolerance.get("unit")
        if tol < 0:
            raise InvalidRuleError(f"{rid}.tolerance 不得为负")
        if kind == "length":
            if unit == "mm":
                tol /= 10
            elif unit != "cm":
                raise InvalidRuleError(f"{rid}.tolerance 单位必须为 cm 或 mm")
            tolerance = {"value": round(tol, 3), "unit": "cm"}
        elif kind == "line_spacing" and expected.get("mode") == "exact":
            if unit == "cm":
                tol *= 72 / 2.54
            elif unit != "pt":
                raise InvalidRuleError(f"{rid}.tolerance 单位必须为 pt 或 cm")
            tolerance = {"value": round(tol, 2), "unit": "pt"}
        elif kind in {"font_size", "signed_pt"}:
            if unit != "pt":
                raise InvalidRuleError(f"{rid}.tolerance 单位必须为 pt")
            tolerance = {"value": tol, "unit": "pt"}
        else:
            raise InvalidRuleError(f"{rid} 不支持允差")
    return {"id": rid, "scope": scope, "expected": expected,
            "tolerance": tolerance, "severity": severity,
            "required": required, "enabled": enabled}


def compile_rules(raw_rules: list[dict], template_id: str, name: str) -> tuple[list[dict], list[dict]]:
    if not isinstance(raw_rules, list):
        raise InvalidRuleError("rules 必须是列表")
    rules = [normalize_rule(raw) for raw in raw_rules]
    seen = set()
    for rule in rules:
        key = (rule["id"], tuple(sorted(rule["scope"].items())))
        if key in seen:
            raise InvalidRuleError(f"重复检测项：{rule['id']} {rule['scope']}")
        seen.add(key)
    enabled = [r for r in rules if r["enabled"]]
    if not enabled:
        raise InvalidRuleError("请至少启用一项当前可自动检查的规则")
    compiled = []
    groups = {}
    for r in enabled:
        rid, exp = r["id"], r["expected"]
        role = r["scope"].get("role")
        if rid.startswith("page.margin_") or rid == "page.footer_distance":
            key, checker, field = "page-" + rid.split(".")[1], "page_setup", ("footer_distance_cm" if rid == "page.footer_distance" else rid.split(".")[1].replace("margin_", "") + "_cm")
            groups[key] = {"id": key, "name": BY_ID[rid]["label"], "checker": checker,
                           "params": {field: exp["value"],
                                      "tolerance_cm": (r["tolerance"] or {}).get("value", 0.1 if rid == "page.footer_distance" else 0.05)},
                           "severity": r["severity"]}
        elif rid in {"font.cjk", "font.latin", "font.size", "font.bold", "paragraph.alignment"}:
            key = f"font-{role}"
            g = groups.setdefault(key, {"id": key, "name": f"{role} 字体与对齐", "checker": "font_format",
                                        "params": {"role": role}, "severity": r["severity"]})
            field = {"font.cjk": "fonts", "font.latin": "ascii_fonts", "font.size": "size_pt",
                     "font.bold": "bold", "paragraph.alignment": "alignment"}[rid]
            g["params"][field] = [exp["value"], *exp.get("aliases", [])] if field in {"fonts", "ascii_fonts"} else exp["value"]
            if r["required"]:
                g["params"]["required"] = True
        elif rid == "paragraph.line_spacing":
            key = f"line-{role}"
            groups[key] = {"id": key, "name": f"{role} 行距", "checker": "line_spacing", "severity": r["severity"],
                           "params": {"roles": [role], "line_pt": exp["value"],
                                      "tolerance_pt": (r["tolerance"] or {}).get("value", 0.5)}}
        elif rid == "font.character_spacing":
            key = f"char-{role}"
            groups[key] = {"id": key, "name": f"{role} 字符间距", "checker": "char_spacing", "severity": r["severity"],
                           "params": {"roles": [role], "spacing_pt": exp["value"],
                                      "tolerance_pt": (r["tolerance"] or {}).get("value", 0.05)}}
        elif rid == "page_number.different_odd_even":
            groups["odd-even-setting"] = {
                "id": "odd-even-setting", "name": "奇偶页不同",
                "checker": "odd_even_setting",
                "params": {"enabled": exp["value"]}, "severity": r["severity"],
            }
        elif rid in PAGE_NUMBER_IDS:
            key = "page-number"
            g = groups.setdefault(key, {"id": key, "name": "页码", "checker": "page_number",
                                        "params": {}, "severity": r["severity"]})
            field = {"page_number.alignment": "alignment", "page_number.font_cjk": "fonts",
                     "page_number.font_size": "size_pt"}.get(rid)
            if field:
                g["params"][field] = [exp["value"], *exp.get("aliases", [])] if field == "fonts" else exp["value"]
        elif rid.startswith("structural."):
            checker = {"secrecy_inner_space": "secrecy", "heading_numbering": "heading_number",
                       "attachment_indent": "attachment", "attachment_blank_before": "attachment",
                       "attachment_trailing_punct": "attachment", "date_format": "signature"}.get(rid.split(".")[1])
            if checker is None:
                raise InvalidRuleError(f"{rid} 当前无法编译")
            g = groups.setdefault(checker, {"id": checker, "name": BY_ID[rid]["label"], "checker": checker,
                                             "params": {}, "severity": r["severity"]})
            field = {"secrecy_inner_space": "inner_space", "attachment_indent": "indent_chars",
                     "attachment_blank_before": "blank_lines_before",
                     "attachment_trailing_punct": "forbid_trailing_punct", "date_format": "date_format"}.get(rid.split(".")[1])
            if field:
                g["params"][field] = "chinese" if rid == "structural.date_format" else exp["value"]
            if r["required"]:
                g["params"]["required"] = True
    # A grouped checker has one severity; reject conflicting atom settings.
    for group in groups.values():
        members = [r for r in enabled if (
            (group["id"] == f"font-{r['scope'].get('role')}" and r["id"] in
             {"font.cjk", "font.latin", "font.size", "font.bold", "paragraph.alignment"})
            or (group["id"] == "page-number" and r["id"] in PAGE_NUMBER_IDS)
        )]
        if len({r["severity"] for r in members}) > 1:
            raise InvalidRuleError(f"{group['id']} 中的检测项级别不同，当前合并检查器要求级别一致")
    compiled = list(groups.values())
    validate_ruleset({"meta": {"id": template_id, "name": name}, "rules": compiled}, template_id)
    return rules, compiled


