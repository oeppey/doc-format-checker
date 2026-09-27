"""合成语料回归：两种版式的 Golden、单项违规及错字注入。"""
from __future__ import annotations

import os
import zipfile

import pytest

from document_checker.cli import RULES_DIR
from document_checker.rule_engine import RuleEngine
from document_checker.synth.corpus import build_corpus
from document_checker.synth.golden import build_cfg
from document_checker.synth.sample_gen import build_doc
from document_checker.typo.confusion import inject_typos_docx
from document_checker.typo.pipeline import run_typo_check
from document_checker.typo.detector import HeuristicDetector
from document_checker.typo.corrector import HeuristicCorrector


@pytest.fixture(scope="session", params=("dazi", "xiaozi"))
def corpus(request, tmp_path_factory):
    outdir = tmp_path_factory.mktemp(f"corpus_{request.param}")
    gold = build_corpus(RULES_DIR, request.param, str(outdir))
    return str(outdir), gold


@pytest.fixture(scope="session")
def engine():
    return RuleEngine(RULES_DIR)


def _error_rule_ids(engine, path, doc_type):
    report = engine.check(path, doc_type)
    return {f.rule_id for f in report.findings if f.severity == "error"}


def _relevant_xml(path):
    with zipfile.ZipFile(path) as docx:
        return {
            name: docx.read(name)
            for name in ("word/document.xml", "word/footer1.xml")
            if name in docx.namelist()
        }


def test_golden_clean(corpus, engine):
    outdir, gold = corpus
    got = _error_rule_ids(
        engine, os.path.join(outdir, "golden.docx"), gold["doc_type"]
    )
    assert got == set(), f"{gold['doc_type']} Golden 不应有 error，实际：{got}"


def test_mutation_cases(corpus, engine):
    outdir, gold = corpus
    baseline = _relevant_xml(os.path.join(outdir, "golden.docx"))
    failures = []
    for case in gold["cases"]:
        if case.get("skipped"):
            continue
        path = os.path.join(outdir, case["file"])
        if _relevant_xml(path) == baseline:
            failures.append(f"{case['case_id']}: 生成的 DOCX 与 Golden 没有相关 XML 差异")
            continue
        got = _error_rule_ids(engine, path, gold["doc_type"])
        missing = set(case["expected_findings"]) - got
        if missing:
            failures.append(
                f"{case['case_id']}: 期望 {case['expected_findings']}，实际 {sorted(got)}"
            )
    assert not failures, "\n".join(failures)


def test_typo_inject_and_detect(tmp_path):
    """错字注入 → 启发式检测/纠错；不依赖模型或 LLM。"""
    cfg = build_cfg(RULES_DIR, "dazi")
    golden = tmp_path / "golden.docx"
    poisoned = tmp_path / "poisoned.docx"
    build_doc(cfg, str(golden))
    injected = inject_typos_docx(str(golden), str(poisoned))
    assert injected, "内置模板应至少能注入一处错字"

    report = run_typo_check(
        str(poisoned),
        detector_backend=(HeuristicDetector(), "heuristic"),
        corrector_backend=(HeuristicCorrector(), "heuristic"),
    )
    confirmed = {(f.original, f.suggestion) for f in report.findings}
    for wrong, right, _para in injected:
        assert (wrong, right) in confirmed, f"注入的错字 {right}→{wrong} 未被检出"
