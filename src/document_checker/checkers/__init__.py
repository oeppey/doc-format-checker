# -*- coding: utf-8 -*-
"""检查器注册表。

新增检查器只需：写函数 → @register("名字") → 在 YAML 规则里用 checker: 名字 引用。
函数签名统一为 (model: DocModel, roles: dict, params: dict) -> list[Finding]。
"""
from __future__ import annotations

from dataclasses import dataclass

CHECKERS: dict[str, callable] = {}


def register(name: str):
    def deco(fn):
        CHECKERS[name] = fn
        return fn
    return deco


@dataclass
class Finding:
    location: str            # 位置描述：第N段 / 页脚 / 第N节
    message: str             # 问题描述
    expected: str = ""       # 期望值
    actual: str = ""         # 实际值
    suggestion: str = ""     # 修复建议
    rule_id: str = ""        # 由规则引擎回填
    rule_name: str = ""
    severity: str = ""       # error / warning / info；为空时由规则引擎取规则默认值


# 导入各检查器模块完成注册
from . import basic      # noqa: E402,F401
from . import structure  # noqa: E402,F401
