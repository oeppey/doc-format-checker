"""Record a strict four-layer typo run for every manual DOCX fixture."""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from document_checker.typo.pipeline import run_typo_check

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--corrector-url", required=True)
    ap.add_argument("--corrector-model", required=True)
    ap.add_argument("--expected-count", type=int, default=19)
    args = ap.parse_args()
    files = sorted(args.fixtures.rglob("*.docx"))
    if len(files) != args.expected_count:
        ap.error(f"Expected {args.expected_count} DOCX files, found {len(files)}")
    cases = []
    batch_start = time.perf_counter()
    for path in files:
        case = {
            "fixture": path.relative_to(args.fixtures).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        start = time.perf_counter()
        try:
            report = run_typo_check(
                str(path), threshold=0.85, use_llm=True,
                detector_model_dir=args.model_dir, detector_device="cuda",
                llm_model=args.corrector_model,
                corrector_base_url=args.corrector_url,
                corrector_protocol="corrected_text",
                require_models=True, use_dict_fallback=True,
            )
            case["report"] = report.to_dict()
            case["pipeline_ok"] = (
                report.detector_name.startswith("electra")
                and report.corrector_name == f"llm:{args.corrector_model}"
                and report.failed_sentences == 0
            )
        except Exception as exc:
            case["pipeline_ok"] = False
            case["error"] = f"{type(exc).__name__}: {exc}"
        case["elapsed_s"] = round(time.perf_counter() - start, 3)
        cases.append(case)
        report_data = case.get("report", {})
        print(json.dumps({
            "fixture": case["fixture"], "elapsed_s": case["elapsed_s"],
            "pipeline_ok": case["pipeline_ok"],
            "status": report_data.get("status"),
            "sentences": report_data.get("total_sentences"),
            "suspect": report_data.get("suspect"),
            "fallback": report_data.get("dict_fallback"),
            "findings": len(report_data.get("findings", [])),
            "error": case.get("error"),
        }, ensure_ascii=False), flush=True)
    summary = {
        "case_count": len(cases),
        "unique_docx_count": len({case["sha256"] for case in cases}),
        "pipeline_ok_count": sum(case["pipeline_ok"] for case in cases),
        "total_sentences": sum(c.get("report", {}).get("total_sentences", 0) for c in cases),
        "skipped_sentences": sum(c.get("report", {}).get("skipped", 0) for c in cases),
        "suspect_sentences": sum(c.get("report", {}).get("suspect", 0) for c in cases),
        "fallback_findings": sum(c.get("report", {}).get("dict_fallback", 0) for c in cases),
        "failed_sentences": sum(c.get("report", {}).get("failed_sentences", 0) for c in cases),
        "merged_findings": sum(len(c.get("report", {}).get("findings", [])) for c in cases),
        "model_findings": sum(
            sum(f.get("source", "").startswith("llm:") for f in c.get("report", {}).get("findings", []))
            for c in cases
        ),
        "elapsed_s": round(time.perf_counter() - batch_start, 3),
    }
    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": {
            "threshold": 0.85, "device": "cuda", "corrector_model": args.corrector_model,
            "corrector_protocol": "corrected_text", "require_models": True,
            "use_dict_fallback": True,
        },
        "summary": summary, "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["pipeline_ok_count"] == len(cases) else 1

if __name__ == "__main__":
    raise SystemExit(main())
