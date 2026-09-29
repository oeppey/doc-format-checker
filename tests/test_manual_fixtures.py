# -*- coding: utf-8 -*-
"""人工标注样本的严格比对测试。

与 tests/test_synthetic.py 的区别：
- 合成语料断言「期望的规则 ID ⊆ 实际规则 ID」，额外 Finding（误报）不会失败；
- 本测试断言「人工期望 == 实际输出」：每条期望必须匹配到一条不同的实际 Finding，
  且不允许存在任何未匹配的实际 Finding（误报即失败）。

gold.json 中 expected_findings 的匹配字段：
  rule_id           规则 ID（必填）
  severity          error / warning / info（缺省 error）
  paragraph         正文段落号（1 起，含空段）；匹配 location 中的「第N段」
  location          直接匹配 location 子串（如「页脚」），与 paragraph 二选一
  message_contains  message 子串
  expected_contains expected 子串
  actual_contains   actual 子串

known_gaps：经标注但当前检查器或角色层尚未覆盖的条目（当前为表格正文）。
  断言这些条目当前「不被检出」；一旦检查器改进后能检出，测试会失败并提示
  把该条移入 expected_findings——缺口关闭必须显式确认，不允许静默变化。
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import runpy
import zipfile
from types import SimpleNamespace

import pytest

from document_checker.cli import RULES_DIR
from document_checker.rule_engine import RuleEngine
from document_checker.docx_parser import parse_document
from document_checker.role_mapper import map_roles
from document_checker.synth.golden import resolve_doc_type

FIXTURE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "manual")
GOLD_FILES = sorted(glob.glob(os.path.join(FIXTURE_ROOT, "**", "*.gold.json"), recursive=True))


def _gold_id(path: str) -> str:
    return os.path.relpath(path, FIXTURE_ROOT).replace(os.sep, "/")


@pytest.fixture(scope="session")
def engine():
    return RuleEngine(RULES_DIR)


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def _matches(entry: dict, f) -> bool:
    """gold 条目是否匹配一条实际 Finding。"""
    if f.rule_id != entry["rule_id"]:
        return False
    if f.severity != entry.get("severity", "error"):
        return False
    if "paragraph" in entry and f"第{entry['paragraph']}段" not in f.location:
        return False
    if "location" in entry and entry["location"] not in f.location:
        return False
    if "message_contains" in entry and entry["message_contains"] not in f.message:
        return False
    if "expected_contains" in entry and entry["expected_contains"] not in (f.expected or ""):
        return False
    if "actual_contains" in entry and entry["actual_contains"] not in (f.actual or ""):
        return False
    if "run" in entry and f"（run {entry['run']}）" not in f.location:
        return False
    if "field" in entry and entry["field"] not in f.message:
        return False
    return True


def _fmt(f) -> str:
    return (f"[{f.severity}] {f.rule_id} @ {f.location}：{f.message}"
            f"（期望：{f.expected}；实际：{f.actual}）")


@pytest.mark.parametrize("gold_path", GOLD_FILES, ids=[_gold_id(p) for p in GOLD_FILES])
def test_fixture_strict(gold_path, engine):
    """期望 Finding 全部命中（一一对应），且无计划外 Finding。"""
    gold = _load(gold_path)
    docx_path = os.path.join(os.path.dirname(gold_path), gold["file"])
    report = engine.check(docx_path, resolve_doc_type(gold["doc_type"]))

    remaining = list(report.findings)
    failures = []
    for entry in gold.get("expected_findings", []):
        hit = next((f for f in remaining if _matches(entry, f)), None)
        if hit is None:
            failures.append(f"期望未命中：{json.dumps(entry, ensure_ascii=False)}")
        else:
            remaining.remove(hit)

    # known_gaps 不算计划外 Finding（它们本就不应被检出，见 test_known_gaps_still_open）
    gaps = gold.get("known_gaps", [])
    unexpected = [f for f in remaining if not any(_matches(g, f) for g in gaps)]
    for f in unexpected:
        failures.append(f"计划外 Finding（误报？）：{_fmt(f)}")

    assert not failures, f"{gold['file']}：\n" + "\n".join(failures)


@pytest.mark.parametrize("gold_path", GOLD_FILES, ids=[_gold_id(p) for p in GOLD_FILES])
def test_known_gaps_still_open(gold_path, engine):
    """known_gaps 条目当前不应被检出；若能检出说明缺口已修复，需人工确认并移动条目。"""
    gold = _load(gold_path)
    gaps = gold.get("known_gaps", [])
    docx_path = os.path.join(os.path.dirname(gold_path), gold["file"])
    report = engine.check(docx_path, resolve_doc_type(gold["doc_type"]))
    closed = [g for g in gaps if any(_matches(g, f) for f in report.findings)]
    assert not closed, (
        f"{gold['file']}：以下 known_gaps 已能被检出，缺口疑似修复，"
        f"请确认后移入 expected_findings：\n"
        + "\n".join(json.dumps(g, ensure_ascii=False) for g in closed)
    )


def _resolve_parse_location(model, location: str):
    if location == "sections":
        return model
    if location == "footer":
        return model
    if location.startswith("sections/"):
        return model.sections[int(location.split("/")[1]) - 1]
    if location.startswith("body/p"):
        parts = location.split("/")
        para = model.paragraphs[int(parts[1][1:]) - 1]
        return para.runs[int(parts[2][3:]) - 1] if len(parts) == 3 else para
    if location.startswith("table"):
        parts = location.split("/")
        para_path = "/".join(parts[:3])
        para = next(p for p in model.table_paragraphs if p.location == para_path)
        return para.runs[int(parts[3][3:]) - 1] if len(parts) == 4 else para
    if location.startswith("footer/"):
        parts = location.split("/")
        kind = parts[1]
        number = int(parts[2][1:])
        paras = [p for p in model.footer_paras if p.kind == kind]
        return paras[number - 1]
    raise AssertionError(f"未知解析标注位置：{location}")


@pytest.mark.parametrize("gold_path", GOLD_FILES, ids=[_gold_id(p) for p in GOLD_FILES])
def test_parse_expectations(gold_path):
    gold = _load(gold_path)
    assert gold.get("parse_expectations"), f"{gold['file']} 缺少解析层期望"
    docx_path = os.path.join(os.path.dirname(gold_path), gold["file"])
    model = parse_document(docx_path)
    for entry in gold["parse_expectations"]:
        target = _resolve_parse_location(model, entry["location"])
        prop = entry["property"]
        if prop == "section_count":
            actual = len(model.sections)
        elif prop == "footer_para_count":
            actual = len(model.footer_paras)
        elif prop == "text_prefix":
            actual = target.text[:len(entry["value"])]
        else:
            actual = getattr(target, prop)
        expected = entry["value"]
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            assert actual is not None and abs(actual - expected) <= entry.get("tolerance", 0.01), (
                f"{gold['file']} {entry['location']}.{prop}: {actual!r} != {expected!r}")
        else:
            assert actual == expected, (
                f"{gold['file']} {entry['location']}.{prop}: {actual!r} != {expected!r}")
    assert not gold.get("parse_known_gaps"), (
        f"{gold['file']} 仍有解析层缺口：{gold['parse_known_gaps']}")


@pytest.mark.parametrize("gold_path", GOLD_FILES, ids=[_gold_id(p) for p in GOLD_FILES])
def test_role_labels(gold_path):
    gold = _load(gold_path)
    docx_path = os.path.join(os.path.dirname(gold_path), gold["file"])
    model = parse_document(docx_path)
    _roles, para_role = map_roles(model)
    gaps = {entry["location"] for entry in gold.get("role_known_gaps", [])}
    labels = gold.get("role_labels", [])
    listed = [entry["location"] for entry in labels]
    expected = {
        p.location for p in model.paragraphs + model.table_paragraphs if not p.is_blank
    }
    assert len(listed) == len(set(listed)), f"{gold['file']} 存在重复角色标注"
    assert set(listed) == expected, (
        f"{gold['file']} 角色标注缺少 {sorted(expected - set(listed))}；"
        f"多出 {sorted(set(listed) - expected)}")
    assert gaps <= set(listed), f"{gold['file']} role_known_gaps 没有对应角色标注"
    for label in labels:
        location = label["location"]
        if location in gaps:
            continue
        if not location.startswith("body/p"):
            pytest.fail(f"{gold['file']} 未标注为 role_known_gaps：{location}")
        index = int(location.split("/")[1][1:]) - 1
        assert para_role.get(index) == label["role"], (
            f"{gold['file']} {location}: {para_role.get(index)!r} != {label['role']!r}")



def test_finding_match_contract():
    finding = SimpleNamespace(
        rule_id="font-body", severity="error",
        location="第4段「正文」（run 2）", message="「body」中文字体不符合要求",
        expected="方正仿宋_GBK", actual="宋体",
    )
    correct = {"rule_id": "font-body", "paragraph": 4, "run": 2, "field": "中文字体"}
    assert _matches(correct, finding)
    assert not _matches({**correct, "run": 1}, finding)
    assert not _matches({**correct, "field": "字号"}, finding)


def test_gold_metadata_and_duplicate_declarations():
    groups: dict[str, list[tuple[str, dict]]] = {}
    required = {"file", "doc_type", "purpose", "annotated_by", "annotated_at",
                "annotation_method", "role_labels", "parse_expectations", "expected_findings"}
    finding_fields = {"rule_id", "severity", "paragraph", "location", "run", "field",
                      "message_contains", "expected_contains", "actual_contains", "reason"}
    for gold_path in GOLD_FILES:
        gold = _load(gold_path)
        assert not required - gold.keys(), f"{gold_path}: 缺少 {sorted(required - gold.keys())}"
        for key in ("expected_findings", "known_gaps"):
            for entry in gold.get(key, []):
                assert not entry.keys() - finding_fields, (
                    f"{gold_path}: {key} 中有未知字段 {sorted(entry.keys() - finding_fields)}")
                assert "rule_id" in entry and ("paragraph" in entry or "location" in entry)
        docx_path = os.path.join(os.path.dirname(gold_path), gold["file"])
        with zipfile.ZipFile(docx_path) as archive:
            parts = [(name, archive.read(name)) for name in sorted(archive.namelist())]
        fingerprint = hashlib.sha256()
        for name, data in parts:
            fingerprint.update(name.encode("utf-8"))
            fingerprint.update(b"\0")
            fingerprint.update(data)
        groups.setdefault(fingerprint.hexdigest(), []).append((gold["file"], gold))
    for duplicate_cases in groups.values():
        ids = {gold.get("shared_baseline_id") for _, gold in duplicate_cases}
        if len(duplicate_cases) > 1:
            assert len(ids) == 1 and None not in ids, (
                f"重复 DOCX 必须显式声明共同底稿：{[name for name, _ in duplicate_cases]}")
        else:
            assert ids == {None}, (
                f"单独 DOCX 不应再声明共享底稿：{duplicate_cases[0][0]}")



def test_new_counterexamples_rebuild_byte_for_byte(tmp_path):
    script = os.path.join(os.path.dirname(__file__), "fixtures", "build_manual_fixtures.py")
    namespace = runpy.run_path(script)
    for name in ("build_17_secrecy_after_title", "build_18_page_field_empty_result",
                 "build_19_attachment_one_ideographic_space"):
        builder = namespace[name]
        builder.__globals__["OUT_ROOT"] = str(tmp_path)
        generated = builder()
        relative = os.path.relpath(generated, tmp_path)
        saved = os.path.join(FIXTURE_ROOT, relative)
        with zipfile.ZipFile(generated) as actual, zipfile.ZipFile(saved) as expected:
            assert sorted(actual.namelist()) == sorted(expected.namelist())
            assert all(actual.read(part) == expected.read(part)
                       for part in actual.namelist()), f"{relative} 与生成脚本不一致"


@pytest.mark.parametrize("fixture", [
    "heading/10_heading_number_in_body_bad.gold.json",
    "signature/11_signature_date_format_bad.gold.json",
    "signature/12_signature_blank_lines_bad.gold.json",
])
def test_provisional_business_decisions_documented(fixture):
    gold = _load(os.path.join(FIXTURE_ROOT, fixture))
    for field in ("basis", "working_assumption", "business_confirmation"):
        assert isinstance(gold.get(field), str) and gold[field].strip(), (fixture, field)
    assert "待业务人工复核" in gold["annotated_by"]
