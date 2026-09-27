# -*- coding: utf-8 -*-
"""合成语料回归测试：规则 → 生成 → 注错 → Checker → Gold 闭环。

需求变更工作流：改 rules/*.yaml → pytest 重新生成语料并断言，无需手工改 Word。

断言约定：
  - golden.docx：零 error 级 finding（不允许误报）；
  - wrong_<case>.docx：expected_findings ⊆ 实际 error 规则集（不允许漏报）。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.rule_engine import RuleEngine            # noqa: E402
from src.synth.corpus import build_corpus         # noqa: E402
from src.synth.golden import build_cfg            # noqa: E402
from src.sample_gen import build_doc              # noqa: E402
from src.typo.confusion import inject_typos_docx  # noqa: E402
from src.typo.pipeline import run_typo_check      # noqa: E402
from src.typo.detector import HeuristicDetector   # noqa: E402
from src.typo.corrector import HeuristicCorrector # noqa: E402

RULES = os.path.join(ROOT, "rules")


@pytest.fixture(scope="session")
def corpus_dazi(tmp_path_factory):
    outdir = tmp_path_factory.mktemp("corpus_dazi")
    gold = build_corpus(RULES, "dazi", str(outdir))
    return str(outdir), gold


@pytest.fixture(scope="session")
def engine():
    return RuleEngine(RULES)


def _error_rule_ids(engine, path, doc_type):
    report = engine.check(path, doc_type)
    return {f.rule_id for f in report.findings if f.severity == "error"}


def test_golden_clean(corpus_dazi, engine):
    outdir, gold = corpus_dazi
    got = _error_rule_ids(engine, os.path.join(outdir, "golden.docx"), gold["doc_type"])
    assert got == set(), f"Golden Document 不应有任何 error 级 finding，实际：{got}"


def test_mutation_cases(corpus_dazi, engine):
    outdir, gold = corpus_dazi
    failures = []
    for case in gold["cases"]:
        if case.get("skipped"):
            continue
        got = _error_rule_ids(engine, os.path.join(outdir, case["file"]), gold["doc_type"])
        missing = set(case["expected_findings"]) - got
        if missing:
            failures.append(f"{case['case_id']}: 期望 {case['expected_findings']}，实际 {sorted(got)}")
    assert not failures, "存在漏报：\n" + "\n".join(failures)


def test_golden_xiaozi(tmp_path, engine):
    outdir = tmp_path / "corpus_xiaozi"
    gold = build_corpus(RULES, "xiaozi", str(outdir))
    got = _error_rule_ids(engine, str(outdir / "golden.docx"), gold["doc_type"])
    assert got == set(), f"小字版 Golden 不应有 error，实际：{got}"


def test_typo_inject_and_detect(tmp_path):
    """错字注入 → 启发式检测/纠错（不依赖模型与 LLM，保证 CI 可跑）。"""
    cfg = build_cfg(RULES, "dazi")
    golden = tmp_path / "golden.docx"
    poisoned = tmp_path / "poisoned.docx"
    build_doc(cfg, str(golden))
    injected = inject_typos_docx(str(golden), str(poisoned))
    assert injected, "内置模板应至少能注入一处错字"

    report = run_typo_check(
        str(poisoned),
        detector_backend=(HeuristicDetector(), "heuristic"),
        corrector_backend=(HeuristicCorrector(), "heuristic"))
    confirmed = {(f.original, f.suggestion) for f in report.findings}
    for wrong, right, _para in injected:
        assert (wrong, right) in confirmed, f"注入的错字 {right}→{wrong} 未被检出"
