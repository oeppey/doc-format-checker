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


def test_dict_fallback_context_guard():
    from document_checker.typo.confusion import dict_fallback_fixes

    # 跨界拼接不报
    assert dict_fallback_fixes("本轮投资全部到位，工作完成。") == []
    assert dict_fallback_fixes("法官理应熟悉相关法律条文。") == []
    assert dict_fallback_fixes("各单位按排名顺序依次申报。") == []
    assert dict_fallback_fixes("这项工作一贯切实有效推进。") == []
    # 真错字仍报
    fixes = dict_fallback_fixes("服务业发展资全官理办法")
    assert [(f["原文"], f["offset"]) for f in fixes] == [("资全", 5), ("官理", 7)]
    assert dict_fallback_fixes("紧密围绕决策布署开展工作。")
    # 监官已收录（财政部当地监管局为固定机构名）
    fixes = dict_fallback_fixes("并抄送财政部当地监官局。")
    assert [(f["原文"], f["改为"]) for f in fixes] == [("监官", "监管")]


def test_cross_validation_drops_off_suspect_fix(tmp_path):
    """模型建议位置不在初筛嫌疑范围内 → 低置信过滤；在范围内 → 保留。"""
    from document_checker.typo.detector import SuspectResult

    docx = tmp_path / "cross.docx"
    doc = Document()
    doc.add_paragraph("依法依规追究相应责任，构成犯罪追究刑责。")
    doc.save(docx)

    class FlagDetector:
        def detect(self, sentences):
            return [SuspectResult(0.9, [(7, "应", 0.9)])]  # 只标「应」

    class MixedCorrector:
        def correct(self, sentence, suspect_chars=None):
            return [
                {"原文": "依", "改为": "一", "理由": "幻觉", "offset": 0},   # 不在嫌疑范围
                {"原文": "应", "改为": "因", "理由": "命中", "offset": 7},   # 在嫌疑范围
            ]

    report = run_typo_check(
        str(docx),
        detector_backend=(FlagDetector(), "electra:mock"),
        corrector_backend=(MixedCorrector(), "llm:mock"),
        use_dict_fallback=False,
    )
    assert report.dropped_suggestions == 1
    assert report.dropped_detail[0]["original"] == "依"
    assert len(report.findings) == 1
    assert report.findings[0].original == "应"


def test_punct_only_suspect_skips_corrector(tmp_path):
    """嫌疑字全是标点时不调精检，计数可追踪。"""
    from document_checker.typo.detector import SuspectResult

    docx = tmp_path / "punct.docx"
    doc = Document()
    doc.add_paragraph("地方财政部门、业务主管部门共同推进工作。")
    doc.save(docx)

    class PunctDetector:
        def detect(self, sentences):
            return [SuspectResult(0.99, [(5, "、", 0.99)])]

    calls = []

    class CountingCorrector:
        def correct(self, sentence, suspect_chars=None):
            calls.append(sentence)
            return []

    report = run_typo_check(
        str(docx),
        detector_backend=(PunctDetector(), "electra:mock"),
        corrector_backend=(CountingCorrector(), "llm:mock"),
        use_dict_fallback=False,
    )
    assert report.punct_filtered == 1
    assert calls == []
    assert report.failed_sentences == 0


def test_validator_rejection_is_not_failure(tmp_path):
    """模型整句改写被校验器拒绝 → 记校验拒绝，不记精检失败，状态不受影响。"""
    from document_checker.typo.detector import SuspectResult

    docx = tmp_path / "reject.docx"
    doc = Document()
    doc.add_paragraph("今天我们开展文档检查工作，确保质量可靠。")
    doc.save(docx)

    class FlagDetector:
        def detect(self, sentences):
            return [SuspectResult(0.9, [(3, "展", 0.9)])]

    seen = []
    corrector = OpenAICorrector(
        model="twnlp/ChineseErrorCorrector4-4B", base_url="http://127.0.0.1:8000/v1",
        client=_mock_client("今天，我们认真开展文档检查与质量保障工作，确保成果可靠。", seen),
    )
    report = run_typo_check(
        str(docx),
        detector_backend=(FlagDetector(), "electra:mock"),
        corrector_backend=(corrector, "llm:mock"),
        use_dict_fallback=False,
    )
    assert report.rejected_sentences == 1
    assert report.failed_sentences == 0
    assert report.status != "运行失败"
    assert "校验拒绝" in report.render_markdown()
    assert "未通过校验" in report.dropped_detail[0]["reason"]


def test_service_error_is_failure(tmp_path):
    """HTTP 服务错误仍是真失败，状态为运行失败。"""
    from document_checker.typo.detector import SuspectResult

    docx = tmp_path / "svc_fail.docx"
    doc = Document()
    doc.add_paragraph("今天我们开展文档检查工作，确保质量可靠。")
    doc.save(docx)

    class FlagDetector:
        def detect(self, sentences):
            return [SuspectResult(0.9, [(3, "展", 0.9)])]

    corrector = OpenAICorrector(
        model="twnlp/ChineseErrorCorrector4-4B", base_url="http://127.0.0.1:8000/v1",
        client=_mock_client("ignored", status=503),
    )
    report = run_typo_check(
        str(docx),
        detector_backend=(FlagDetector(), "electra:mock"),
        corrector_backend=(corrector, "llm:mock"),
        use_dict_fallback=False,
    )
    assert report.failed_sentences == 1
    assert report.rejected_sentences == 0
    assert report.status == "运行失败"


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
