# -*- coding: utf-8 -*-
"""语料批量产出：Golden Document + 每个变异一份 wrong_*.docx + gold.json。

gold.json 结构：
{
  "doc_type": "chengbaogao_dazi",
  "golden":  {"file": "golden.docx", "expected_findings": []},
  "cases":   [{"case_id": "title_font", "file": "wrong_title_font.docx",
               "expected_findings": ["font-title"], "description": "..."}]
}
"""
from __future__ import annotations

import json
import os

from ..sample_gen import DEFAULT_CONTENT, build_doc
from .golden import build_cfg, resolve_doc_type
from .mutations import MUTATIONS


def build_corpus(rules_dir: str, doc_type: str, outdir: str,
                 content: dict | None = None) -> dict:
    doc_type = resolve_doc_type(doc_type)
    os.makedirs(outdir, exist_ok=True)
    cfg = build_cfg(rules_dir, doc_type)
    content = content or DEFAULT_CONTENT

    build_doc(cfg, os.path.join(outdir, "golden.docx"), content)

    cases = []
    for cid, m in MUTATIONS.items():
        if cid == "attachment_punct" and not content.get("attachment"):
            cases.append({"case_id": cid, "skipped": True,
                          "reason": "内容无附件说明，无法注入", "expected_findings": []})
            continue
        fname = f"wrong_{cid}.docx"
        build_doc(cfg, os.path.join(outdir, fname), content, mutations=[cid])
        cases.append({"case_id": cid, "file": fname,
                      "expected_findings": m["expected"], "description": m["desc"]})

    gold = {"doc_type": doc_type,
            "golden": {"file": "golden.docx", "expected_findings": []},
            "cases": cases}
    with open(os.path.join(outdir, "gold.json"), "w", encoding="utf-8") as fp:
        json.dump(gold, fp, ensure_ascii=False, indent=2)
    return gold
