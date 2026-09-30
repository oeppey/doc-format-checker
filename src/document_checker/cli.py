#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公文格式检查 CLI。

用法：
  检查：  python main.py check 文件.docx [--type chengbaogao_dazi] [--report out.md] [--json out.json]
  造数：  python main.py generate --type dazi --out 样本.docx [--violate body_font,line_spacing]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .rule_engine import RuleEngine
from .synth.sample_gen import build_doc
from .synth.golden import build_cfg, resolve_doc_type
from .synth.mutations import MUTATIONS
from .synth.corpus import build_corpus
from .synth.import_docx import extract_content
from .typo.pipeline import run_typo_check
from .typo.confusion import inject_typos_docx, CONFUSION_PAIRS

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
TYPE_ALIAS = {"dazi": "chengbaogao_dazi", "xiaozi": "chengbaogao_xiaozi"}


def cmd_check(args):
    try:
        engine = RuleEngine(args.rules)
        doc_type = TYPE_ALIAS.get(args.type, args.type) if args.type else None
        report = engine.check(args.docx, doc_type)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"检查无法完成：{exc}", file=sys.stderr)
        return 2
    counts = report.counts()
    print(f"文件：{report.file}")
    print(f"适用规则集：{report.ruleset_name}（{report.doc_type}）")
    print(f"检查状态：{report.status}")
    print(f"规则：共 {len(report.rule_results)} 条；问题：错误 {counts['error']}，"
          f"警告 {counts['warning']}，提示 {counts['info']}")
    for f in report.findings:
        print(f"  [{f.severity:7s}] {f.rule_name} @ {f.location}：{f.message}"
              f"（期望：{f.expected}；实际：{f.actual}）")
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fp:
            fp.write(report.render_markdown())
        print(f"Markdown 报告：{args.report}")
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump(report.to_dict(), fp, ensure_ascii=False, indent=2)
        print(f"JSON 报告：{args.json}")
    if report.status in ("未检查", "运行失败"):
        return 2
    return 1 if counts["error"] else 0


def cmd_generate(args):
    mutations = [v.strip() for v in args.violate.split(",") if v.strip()] if args.violate else []
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    cfg = build_cfg(args.rules, args.type)
    applied = build_doc(cfg, args.out, mutations=mutations)
    print(f"已生成：{args.out}")
    if applied:
        print("注入违规：")
        for a in applied:
            print(f"  - {a}")
    else:
        print("未注入违规（合规样本）")
    return 0


def cmd_synth(args):
    gold = build_corpus(args.rules, args.type, args.outdir)
    n_ok = sum(1 for c in gold["cases"] if not c.get("skipped"))
    print(f"语料已生成：{args.outdir}")
    print(f"  golden.docx + {n_ok} 份 wrong_*.docx + gold.json（文书类型：{gold['doc_type']}）")
    for c in gold["cases"]:
        if c.get("skipped"):
            print(f"  - {c['case_id']}: 跳过（{c['reason']}）")
        else:
            print(f"  - {c['case_id']}: {c['file']} → 期望命中 {c['expected_findings']}")
    return 0


def cmd_import(args):
    content = extract_content(args.src)
    mutations = [v.strip() for v in args.violate.split(",") if v.strip()] if args.violate else []
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    cfg = build_cfg(args.rules, args.type)
    applied = build_doc(cfg, args.out, content=content, mutations=mutations)
    print(f"已导入：{args.src} → {args.out}")
    print(f"  标题：{content['title'][:40]}")
    kinds = {}
    for k, _ in content["blocks"]:
        kinds[k] = kinds.get(k, 0) + 1
    print(f"  结构：{dict(kinds)}；署名：{content['signature']}；日期：{content['date']}")
    if content.get("_skipped"):
        print(f"  跳过对象（表格/图片/附件行等）：{content['_skipped']} 处")
    if applied:
        print("  注入违规：")
        for a in applied:
            print(f"    - {a}")
    return 0


def cmd_typo(args):
    try:
        report = run_typo_check(
            args.docx, threshold=args.threshold, use_llm=not args.no_llm,
            llm_model=args.model, detector_model_dir=args.detector_model_dir,
            detector_device=args.device, corrector_base_url=args.corrector_url,
            corrector_protocol=args.corrector_protocol, require_models=args.require_models,
            use_dict_fallback=not args.no_dict_fallback)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"错字检查无法完成：{exc}", file=sys.stderr)
        return 2
    print(f"文件：{report.file}")
    print(f"状态：{report.status}")
    print(f"检测器：{report.detector_name}；精检：{report.corrector_name}")
    print(f"句子 {report.total_sentences}，过滤 {report.skipped}，"
          f"嫌疑 {report.suspect}，确认 {len(report.findings)} 处，失败 {report.failed_sentences} 句")
    for f in report.findings:
        print(f"  [{f.location}] 「{f.original}」→「{f.suggestion}」 {f.reason}"
              f"（嫌疑分 {f.score:.2f}）")
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fp:
            fp.write(report.render_markdown())
        print(f"Markdown 报告：{args.report}")
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump(report.to_dict(), fp, ensure_ascii=False, indent=2)
        print(f"JSON 报告：{args.json}")
    if report.status in ("未检查", "运行失败"):
        return 2
    return 1 if report.findings else 0


def cmd_inject(args):
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()] or None
    injected = inject_typos_docx(args.src, args.out, pairs)
    print(f"已注入 {len(injected)} 处错字 → {args.out}")
    for wrong, right, pi in injected:
        print(f"  第{pi}段：{right} → {wrong}（注入错误）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="公文格式检查工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="检查 Word 公文")
    c.add_argument("docx")
    c.add_argument("--type", help="文书类型（dazi/xiaozi 或规则集 id），缺省自动识别")
    c.add_argument("--rules", default=RULES_DIR, help="规则目录")
    c.add_argument("--report", help="Markdown 报告输出路径")
    c.add_argument("--json", help="JSON 报告输出路径")
    c.set_defaults(fn=cmd_check)

    g = sub.add_parser("generate", help="生成合成样本")
    g.add_argument("--type", required=True, choices=["dazi", "xiaozi"])
    g.add_argument("--out", required=True)
    g.add_argument("--rules", default=RULES_DIR)
    g.add_argument("--violate", default="", help=f"逗号分隔的违规注入：{', '.join(MUTATIONS)}")
    g.set_defaults(fn=cmd_generate)

    s = sub.add_parser("synth", help="批量生成评测语料（golden + wrong_* + gold.json）")
    s.add_argument("--type", required=True, choices=["dazi", "xiaozi"])
    s.add_argument("--outdir", required=True)
    s.add_argument("--rules", default=RULES_DIR)
    s.set_defaults(fn=cmd_synth)

    i = sub.add_parser("import", help="导入公开公文内容并重排为目标格式")
    i.add_argument("src", help="来源 .docx（公开公文）")
    i.add_argument("--type", required=True, choices=["dazi", "xiaozi"])
    i.add_argument("--out", required=True)
    i.add_argument("--rules", default=RULES_DIR)
    i.add_argument("--violate", default="", help="同 generate")
    i.set_defaults(fn=cmd_import)

    t = sub.add_parser("typo", help="错别字检查")
    t.add_argument("docx")
    t.add_argument("--threshold", type=float, default=0.85, help="ELECTRA 字级嫌疑阈值")
    t.add_argument("--no-llm", action="store_true", help="不调用大模型精检（启发式兜底）")
    t.add_argument("--no-dict-fallback", action="store_true", help="关闭确定性词表兜底")
    t.add_argument("--model", help="LLM 型号（或设置 DOCUMENT_CHECKER_CORRECTOR_MODEL）")
    t.add_argument("--detector-model-dir", help="ELECTRA 本地模型目录（或设置 CED_MODEL_DIR）")
    t.add_argument("--device", default="auto", help="ELECTRA 设备：auto、cpu 或 cuda")
    t.add_argument("--corrector-url", help="4B/27B OpenAI 兼容服务地址，包含 /v1")
    t.add_argument("--corrector-protocol", choices=["corrected_text", "json"],
                   help="精检响应格式；4B 默认 corrected_text，其他模型默认 json")
    t.add_argument("--require-models", action="store_true",
                   help="要求真实 ELECTRA 和精检服务；不可用时失败，不启用词表回退")
    t.add_argument("--report", help="Markdown 报告输出路径")
    t.add_argument("--json", help="JSON 报告输出路径")
    t.set_defaults(fn=cmd_typo)

    j = sub.add_parser("inject", help="往 docx 里注入错字（造测试数据）")
    j.add_argument("src")
    j.add_argument("--out", required=True)
    j.add_argument("--pairs", default="",
                   help="逗号分隔的'正确写法'（如 部署,补贴），缺省注入词表中全部能找到的")
    j.set_defaults(fn=cmd_inject)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
