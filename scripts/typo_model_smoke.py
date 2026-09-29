"""Reproducible smoke test for the real ELECTRA and optional correction service."""
from __future__ import annotations

import argparse
import json
import time

from document_checker.typo.detector import ElectraDetector
from document_checker.typo.service_corrector import OpenAICorrector

SENTENCES = [
    "今天我们按照规定开展文档审查工作。",
    "项目已经布署完成，请尽快检查结果。",
    "请按排专人负责材料归档工作。",
    "申请人与被申请人已经达成和解协议。",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector-model-dir", required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--corrector-url")
    parser.add_argument("--corrector-model")
    parser.add_argument("--corrector-protocol", choices=["corrected_text", "json"])
    args = parser.parse_args()
    start = time.perf_counter()
    detector = ElectraDetector(args.detector_model_dir, args.threshold, args.device)
    load_s = round(time.perf_counter() - start, 3)
    start = time.perf_counter()
    results = detector.detect(SENTENCES)
    detect_s = round(time.perf_counter() - start, 3)
    output = {
        "detector": "real ELECTRA",
        "device": detector.device,
        "threshold": args.threshold,
        "load_seconds": load_s,
        "detect_seconds": detect_s,
        "truncated": detector.last_truncated,
        "sentences": [],
        "corrector": "not tested: no service configured",
    }
    corrector = None
    if args.corrector_url or args.corrector_model:
        corrector = OpenAICorrector(args.corrector_model, args.corrector_url,
                                    args.corrector_protocol)
        output["corrector"] = f"real service: {corrector.model} ({corrector.protocol})"
    failed = 0
    for sentence, result in zip(SENTENCES, results):
        item = {
            "text": sentence,
            "suspect_chars": None if result is None else result.suspect_chars,
        }
        if corrector is not None and result is not None:
            try:
                item["corrections"] = corrector.correct(sentence, result.suspect_chars)
            except Exception as exc:
                failed += 1
                item["corrector_error"] = f"{type(exc).__name__}: {exc}"
        output["sentences"].append(item)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
