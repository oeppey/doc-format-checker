"""Validate user-editable YAML rules before document checking starts."""
from __future__ import annotations

from numbers import Real

from .checkers import CHECKERS

SEVERITIES = {"error", "warning", "info"}
ROLES = {
    "title", "body", "heading1", "heading2", "heading3", "heading4",
    "secrecy", "wenhao", "attachment", "signature", "date",
}
FIELDS = {
    "page_setup": (set(), {"top_cm", "bottom_cm", "left_cm", "right_cm", "footer_distance_cm", "tolerance_cm"}),
    "font_format": ({"role"}, {"fonts", "ascii_fonts", "size_pt", "bold", "alignment", "required"}),
    "line_spacing": ({"line_pt"}, {"roles", "tolerance_pt"}),
    "char_spacing": (set(), {"roles", "spacing_pt", "tolerance_pt"}),
    "page_number": (set(), {"dash", "alignment", "fonts", "size_pt", "footer_distance_cm", "tolerance_cm"}),
    "odd_even_setting": ({"enabled"}, set()),
    "heading_number": (set(), set()),
    "secrecy": (set(), {"fonts", "size_pt", "bold", "inner_space", "required"}),
    "attachment": (set(), {"indent_chars", "blank_lines_before", "forbid_trailing_punct"}),
    "signature": (set(), {"date_format", "blank_lines_before", "blank_line_spacing_pt", "blank_line_tolerance_pt", "seal_expected"}),
}


class InvalidRuleError(ValueError):
    """A rule file has an unsupported or malformed field."""


def _fail(where: str, message: str) -> None:
    raise InvalidRuleError(f"{where}: {message}")


def _number(value: object, where: str, *, minimum: float = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or value < minimum:
        _fail(where, f"必须是 >= {minimum} 的数字")


def _roles(value: object, where: str) -> None:
    if not isinstance(value, list) or not value or any(
        not isinstance(role, str) or role not in ROLES for role in value
    ):
        _fail(where, f"必须是非空角色列表，可选：{sorted(ROLES)}")


def _fonts(value: object, where: str) -> None:
    if not isinstance(value, list) or not value or any(
        not isinstance(font, str) or not font.strip() for font in value
    ):
        _fail(where, "必须是非空字体名称列表")


def validate_ruleset(data: object, path: str) -> None:
    if not isinstance(data, dict):
        _fail(path, "顶层必须是映射")
    meta = data.get("meta")
    if not isinstance(meta, dict) or not isinstance(meta.get("id"), str) or not meta["id"].strip():
        _fail(path, "meta.id 必须是非空字符串")
    rules = data.get("rules")
    if not isinstance(rules, list):
        _fail(path, "rules 必须是列表")
    seen: set[str] = set()
    for index, rule in enumerate(rules, 1):
        where = f"{path}:rules[{index}]"
        if not isinstance(rule, dict):
            _fail(where, "规则必须是映射")
        rid = rule.get("id")
        if not isinstance(rid, str) or not rid.strip():
            _fail(where, "id 必须是非空字符串")
        if rid in seen:
            _fail(where, f"重复规则 ID：{rid}")
        seen.add(rid)
        where += f"({rid})"
        checker = rule.get("checker")
        if not isinstance(checker, str) or checker not in CHECKERS or checker not in FIELDS:
            _fail(where, f"未知 checker：{checker}")
        if not isinstance(rule.get("severity", "error"), str) or rule.get("severity", "error") not in SEVERITIES:
            _fail(where, "severity 必须是 error、warning 或 info")
        params = rule.get("params", {})
        if not isinstance(params, dict):
            _fail(where, "params 必须是映射")
        required, optional = FIELDS[checker]
        missing = required - params.keys()
        extra = params.keys() - required - optional
        if missing:
            _fail(where, f"缺少参数：{sorted(missing)}")
        if extra:
            _fail(where, f"不支持的参数：{sorted(extra)}")
        for key, value in params.items():
            field = f"{where}.params.{key}"
            if key in {"fonts", "ascii_fonts"}:
                _fonts(value, field)
            elif key == "role":
                if not isinstance(value, str) or value not in ROLES:
                    _fail(field, f"未知角色，可选：{sorted(ROLES)}")
            elif key == "roles":
                _roles(value, field)
            elif key in {"bold", "required", "inner_space", "forbid_trailing_punct", "seal_expected", "enabled"}:
                if not isinstance(value, bool):
                    _fail(field, "必须是布尔值")
            elif key == "alignment":
                if not isinstance(value, str) or value not in {"left", "center", "right"}:
                    _fail(field, "必须是 left、center 或 right")
            elif key == "date_format":
                if value != "chinese":
                    _fail(field, "当前只支持 chinese")
            elif key == "dash":
                if not isinstance(value, str) or not value.strip():
                    _fail(field, "必须是非空字符串")
            elif key in {"indent_chars", "blank_lines_before"}:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    _fail(field, "必须是非负整数")
            elif key in {"size_pt", "line_pt", "blank_line_spacing_pt", "top_cm", "bottom_cm", "left_cm",
                         "right_cm", "footer_distance_cm"}:
                _number(value, field, minimum=0.01)
            elif key in {"spacing_pt", "tolerance_pt", "blank_line_tolerance_pt", "tolerance_cm"}:
                _number(value, field, minimum=0)
        if checker == "font_format" and not any(
            key in params for key in ("fonts", "ascii_fonts", "size_pt", "bold", "alignment")
        ):
            _fail(where, "font_format 至少需要一种待检查属性")
        if checker == "page_setup" and not any(
            key in params for key in ("top_cm", "bottom_cm", "left_cm", "right_cm", "footer_distance_cm")
        ):
            _fail(where, "page_setup 至少需要一项页边距")


