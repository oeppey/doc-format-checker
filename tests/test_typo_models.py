"""Protocol and failure tests for typo model integration."""
from __future__ import annotations

import httpx
import pytest
from docx import Document

from document_checker.typo.detector import get_detector
from document_checker.typo.pipeline import run_typo_check
from document_checker.typo.service_corrector import OpenAICorrector, corrected_text_to_fixes


def _mock_client(content, seen=None, status=200):
    def respond(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_4b_think_output_and_exact_offset(monkeypatch):
    seen = []
    monkeypatch.setenv("DOCUMENT_CHECKER_CORRECTOR_API_KEY", "test-only")
    corrector = OpenAICorrector(
        model="twnlp/ChineseErrorCorrector4-4B", base_url="http://127.0.0.1:8000/v1",
        client=_mock_client("<think>错误类型：错别字</think>\n今天会和，明天会合。", seen),
    )
    fixes = corrector.correct("今天会和，明天会和。")
    assert fixes == [{"原文": "和", "改为": "合", "理由": "模型建议", "offset": 8}]
    assert seen[0].url.path == "/v1/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer test-only"
    assert seen[0].read().decode("utf-8").find("ChineseErrorCorrector4-4B") >= 0


def test_4b_suspect_hint_in_request():
    seen = []
    corrector = OpenAICorrector(
        model="twnlp/ChineseErrorCorrector4-4B", base_url="http://127.0.0.1:8000/v1",
        client=_mock_client("各单位要认真部署工作。", seen), suspect_hint=True,
    )
    corrector.correct("各单位要认真布署工作。", [(6, "布", 0.91)])
    payload = seen[0].read().decode("utf-8")
    assert "疑似错字：「布」" in payload
    seen.clear()
    corrector.correct("各单位要认真布署工作。")
    assert "疑似错字" not in seen[0].read().decode("utf-8")


def test_4b_suspect_hint_off_by_default():
    seen = []
    corrector = OpenAICorrector(
        model="twnlp/ChineseErrorCorrector4-4B", base_url="http://127.0.0.1:8000/v1",
        client=_mock_client("各单位要认真部署工作。", seen),
    )
    corrector.correct("各单位要认真布署工作。", [(6, "布", 0.91)])
    assert "疑似错字" not in seen[0].read().decode("utf-8")


def test_4b_no_change_insert_and_protected_term():
    assert corrected_text_to_fixes("原句不变。", "原句不变。") == []
    assert corrected_text_to_fixes("请参加会议。", "请参加会。") == [
        {"原文": "", "改为": "议", "理由": "模型建议", "offset": 4}
    ]
    with pytest.raises(ValueError, match="受保护"):
        corrected_text_to_fixes("决定不启诉。", "决定不起诉。")


@pytest.mark.parametrize("output", [
    "<think>没有闭合",
    "<think>分析</think>",
    "今天结束项目。",
])
def test_4b_rejects_incomplete_or_rewrite(output):
    with pytest.raises(ValueError):
        corrected_text_to_fixes(output, "今天开展工作。")


def test_27b_json_protocol():
    corrector = OpenAICorrector(
        model="existing-27b", base_url="http://127.0.0.1:8000/v1",
        client=_mock_client('[{"原文":"会和","改为":"会合","理由":"错字"}]'),
    )
    assert corrector.protocol == "json"
    assert corrector.correct("今天会和。")[0]["改为"] == "会合"


def test_service_error_is_not_silent():
    corrector = OpenAICorrector(
        model="existing-27b", base_url="http://127.0.0.1:8000/v1",
        client=_mock_client("ignored", status=503),
    )
    with pytest.raises(httpx.HTTPStatusError):
        corrector.correct("今天会和。")


def test_strict_mode_rejects_missing_models(tmp_path):
    docx = tmp_path / "one.docx"
    doc = Document()
    doc.add_paragraph("今天我们开展文档检查工作。")
    doc.save(docx)
    with pytest.raises(RuntimeError, match="ELECTRA 初筛不可用"):
        run_typo_check(str(docx), detector_model_dir=str(tmp_path / "missing"),
                       require_models=True)
    with pytest.raises(RuntimeError, match="ELECTRA 初筛不可用"):
        get_detector(model_dir=str(tmp_path / "missing"), strict=True)



def test_pipeline_with_mock_openai_service(tmp_path):
    from document_checker.typo.detector import SuspectResult

    docx = tmp_path / "mock_service.docx"
    doc = Document()
    doc.add_paragraph("今天会和，明天会和。")
    doc.save(docx)

    class MockDetector:
        def detect(self, sentences):
            return [SuspectResult(0.9, [(8, "和", 0.9)])]

    corrector = OpenAICorrector(
        model="twnlp/ChineseErrorCorrector4-4B",
        base_url="http://127.0.0.1:8000/v1",
        client=_mock_client("<think>错别字</think>今天会和，明天会合。"),
    )
    report = run_typo_check(
        str(docx),
        detector_backend=(MockDetector(), "electra:mock"),
        corrector_backend=(corrector, "llm:mock"),
    )
    assert report.failed_sentences == 0
    assert len(report.findings) == 1
    assert report.findings[0].sent_start == 8
    assert report.findings[0].original == "和"
    assert report.findings[0].suggestion == "合"


def test_dict_fallback_catches_unflagged_sentence(tmp_path):
    """检测器未标记的句子，词表兜底仍能命中并给出准确位置。"""
    docx = tmp_path / "fallback.docx"
    doc = Document()
    doc.add_paragraph("各单位要认真布署工作，确保任务完成。")
    doc.save(docx)

    class QuietDetector:
        def detect(self, sentences):
            return [None] * len(sentences)

    class QuietCorrector:
        def correct(self, sentence, suspect_chars=None):
            return []

    report = run_typo_check(
        str(docx),
        detector_backend=(QuietDetector(), "electra:mock"),
        corrector_backend=(QuietCorrector(), "llm:mock"),
    )
    assert report.dict_fallback == 1
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.original == "布署" and finding.suggestion == "部署"
    assert finding.source == "词表兜底"
    assert finding.sentence[finding.sent_start:finding.sent_start + 2] == "布署"


def test_dict_fallback_dedupes_model_fix(tmp_path):
    """模型建议与兜底命中同一位置时只保留一条。"""
    docx = tmp_path / "dedup.docx"
    doc = Document()
    doc.add_paragraph("各单位要认真布署工作，确保任务完成。")
    doc.save(docx)

    from document_checker.typo.detector import SuspectResult

    class FlagDetector:
        def detect(self, sentences):
            return [SuspectResult(0.9, [(7, "布", 0.9)])]

    class EchoCorrector:
        def correct(self, sentence, suspect_chars=None):
            return [{"原文": "布署", "改为": "部署", "理由": "模型建议", "offset": 7}]

    report = run_typo_check(
        str(docx),
        detector_backend=(FlagDetector(), "electra:mock"),
        corrector_backend=(EchoCorrector(), "llm:mock"),
    )
    assert len(report.findings) == 1
    assert report.findings[0].source == "词表兜底"


def test_dict_fallback_can_be_disabled(tmp_path):
    docx = tmp_path / "no_fallback.docx"
    doc = Document()
    doc.add_paragraph("各单位要认真布署工作，确保任务完成。")
    doc.save(docx)

    class QuietDetector:
        def detect(self, sentences):
            return [None] * len(sentences)

    class QuietCorrector:
        def correct(self, sentence, suspect_chars=None):
            return []

    report = run_typo_check(
        str(docx),
        detector_backend=(QuietDetector(), "electra:mock"),
        corrector_backend=(QuietCorrector(), "llm:mock"),
        use_dict_fallback=False,
    )
    assert report.dict_fallback == 0
    assert report.findings == []


def test_dict_fallback_fixes_offsets():
    from document_checker.typo.confusion import dict_fallback_fixes

    fixes = dict_fallback_fixes("先布署，再布署。")
    assert [(f["原文"], f["改为"], f["offset"]) for f in fixes] == [
        ("布署", "部署", 1), ("布署", "部署", 5)]
    assert dict_fallback_fixes("部署工作已完成。") == []


def test_strict_mode_requires_corrector_service(tmp_path, monkeypatch):
    from document_checker.typo.detector import SuspectResult

    docx = tmp_path / "no_service.docx"
    doc = Document()
    doc.add_paragraph("今天会和，明天会和。")
    doc.save(docx)

    class MockDetector:
        def detect(self, sentences):
            return [SuspectResult(0.9, [(8, "和", 0.9)])]

    monkeypatch.delenv("DOCUMENT_CHECKER_CORRECTOR_MODEL", raising=False)
    monkeypatch.delenv("DOCUMENT_CHECKER_CORRECTOR_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="精检不可用"):
        run_typo_check(
            str(docx), detector_backend=(MockDetector(), "electra:mock"),
            require_models=True,
        )
