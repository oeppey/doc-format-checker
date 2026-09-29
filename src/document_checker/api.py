"""Local HTTP API for template management and document review."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .docx_parser import parse_document
from .preview import PreviewError, map_findings, render_docx
from .rule_engine import RuleEngine
from .rules_schema import InvalidRuleError
from .standardization import CATALOG, VERSION, compile_rules
from .template_extractor import extract_candidates
from .typo.pipeline import run_typo_check

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data" / "templates"
RULES_DIR = Path(__file__).resolve().parent / "rules"
MAX_DOCX_BYTES = 20 * 1024 * 1024


class TemplateStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        result = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
        return result

    def get(self, template_id: str) -> dict | None:
        try:
            uuid.UUID(template_id)
        except ValueError:
            return None
        path = self.directory / f"{template_id}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, template: dict) -> dict:
        template_id = template.get("id") or str(uuid.uuid4())
        try:
            uuid.UUID(template_id)
        except ValueError as exc:
            raise InvalidRuleError("模板 ID 无效") from exc
        data = dict(template, id=template_id)
        target = self.directory / f"{template_id}.json"
        temp = self.directory / f".{template_id}.tmp"
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, target)
        return data

    def delete(self, template_id: str) -> bool:
        if self.get(template_id) is None:
            return False
        (self.directory / f"{template_id}.json").unlink()
        return True


async def _save_upload(file: UploadFile) -> str:
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "当前后端仅支持 .docx；请将旧版 .doc 另存为 .docx")
    data = await file.read(MAX_DOCX_BYTES + 1)
    if len(data) > MAX_DOCX_BYTES:
        raise HTTPException(413, "DOCX 超过 20 MB 上限")
    if not data.startswith(b"PK"):
        raise HTTPException(400, "文件不是有效的 DOCX ZIP 容器")
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as fp:
        fp.write(data)
        return fp.name


def create_app(*, data_dir: Path = DEFAULT_DATA, rules_dir: Path = RULES_DIR,
               html_path: Path = ROOT / "template-management.html") -> FastAPI:
    app = FastAPI(title="文档质检本地服务", version="0.1.0")
    # 跨域：默认放行本机常见前端端口；服务器部署时用
    # DOCUMENT_CHECKER_CORS_ORIGINS="https://前端域名,http://..." 显式指定。
    origins = [item.strip() for item in os.environ.get(
        "DOCUMENT_CHECKER_CORS_ORIGINS",
        "http://localhost:5173,http://localhost:7100,http://127.0.0.1:5173,http://127.0.0.1:7100",
    ).split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    store = TemplateStore(data_dir)
    review_dir = data_dir.parent / 'reviews'
    review_dir.mkdir(parents=True, exist_ok=True)
    review_slots = asyncio.Semaphore(max(1, int(os.environ.get("DOCUMENT_CHECKER_MAX_REVIEWS", "1"))))

    @app.get("/")
    def index():
        return FileResponse(html_path, media_type="text/html; charset=utf-8")

    @app.get("/frontend-integration.js")
    def frontend_script():
        return FileResponse(ROOT / "frontend-integration.js", media_type="text/javascript; charset=utf-8")

    @app.get("/api/catalog")
    def catalog():
        return {"version": VERSION, "items": CATALOG, "note": "仅 supported 和明确标注的 partial 子集可以启用；需渲染校验的奇偶页留字暂不启用"}

    @app.get("/api/templates")
    def list_templates():
        engine = RuleEngine(str(rules_dir))
        builtins = [
            {"id": f"builtin:{rid}", "name": rs["meta"].get("name", rid),
             "source": "内置 YAML", "description": rs["meta"].get("source", ""),
             "active_rule_count": len(engine._merged_rules(rs)), "builtin": True}
            for rid, rs in engine.rulesets.items()
        ]
        customs = [
            {k: t.get(k) for k in ("id", "name", "source", "description", "active_rule_count")}
            | {"builtin": False}
            for t in store.list()
        ]
        return {"templates": builtins + customs}

    @app.get("/api/templates/{template_id:path}")
    def get_template(template_id: str):
        if template_id.startswith("builtin:"):
            rid = template_id.removeprefix("builtin:")
            engine = RuleEngine(str(rules_dir))
            if rid not in engine.rulesets:
                raise HTTPException(404, "模板不存在")
            return {"id": template_id, "name": engine.rulesets[rid]["meta"].get("name", rid),
                    "builtin": True, "compiled_rules": engine._merged_rules(engine.rulesets[rid])}
        result = store.get(template_id)
        if result is None:
            raise HTTPException(404, "模板不存在")
        return result

    @app.post("/api/templates/extract")
    async def extract(file: UploadFile = File(...)):
        path = await _save_upload(file)
        try:
            return await run_in_threadpool(extract_candidates, path)
        except Exception as exc:
            raise HTTPException(422, f"DOCX 解析失败：{exc}") from exc
        finally:
            Path(path).unlink(missing_ok=True)

    @app.post("/api/templates/validate")
    def validate_template(payload: dict):
        try:
            normalized, compiled = compile_rules(payload.get("rules", []), "preview",
                                                 str(payload.get("name") or "新模板"))
        except (InvalidRuleError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"normalized_rules": normalized, "compiled_rules": compiled,
                "active_rule_count": len(compiled)}

    @app.post("/api/templates")
    def save_template(payload: dict):
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "请填写模板名称")
        template_id = payload.get("id") or str(uuid.uuid4())
        try:
            normalized, compiled = compile_rules(payload.get("rules", []), template_id, name)
            old = store.get(template_id)
            if old is not None and old.get("id") != template_id:
                raise InvalidRuleError("模板 ID 冲突")
            template = store.save({
                "id": template_id, "name": name,
                "source": str(payload.get("source") or "用户上传 DOCX"),
                "description": str(payload.get("description") or ""),
                "catalog_version": VERSION,
                "rules": normalized, "compiled_rules": compiled,
                "active_rule_count": len(compiled),
                "builtin": False,
            })
        except (InvalidRuleError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return template

    @app.delete("/api/templates/{template_id}")
    def delete_template(template_id: str):
        if not store.delete(template_id):
            raise HTTPException(404, "模板不存在或不可删除")
        return {"deleted": True}

    def review_file(review_id: str, filename: str) -> Path:
        try:
            uuid.UUID(review_id)
        except ValueError as exc:
            raise HTTPException(404, "预览不存在") from exc
        target = review_dir / review_id / filename
        if not target.is_file():
            raise HTTPException(404, "预览不存在")
        return target

    @app.get("/api/reviews/{review_id}/pages/{page_number}")
    def preview_page(review_id: str, page_number: int):
        if not 1 <= page_number <= 200:
            raise HTTPException(404, "页码无效")
        return FileResponse(review_file(review_id, f"page-{page_number}.png"),
                            media_type="image/png")

    @app.get("/api/reviews/{review_id}/preview.pdf")
    def preview_pdf(review_id: str):
        return FileResponse(review_file(review_id, "preview.pdf"),
                            media_type="application/pdf")

    @app.delete("/api/reviews/{review_id}")
    def delete_review(review_id: str):
        try:
            uuid.UUID(review_id)
        except ValueError as exc:
            raise HTTPException(404, "预览不存在") from exc
        target = review_dir / review_id
        if not target.is_dir():
            raise HTTPException(404, "预览不存在")
        shutil.rmtree(target)
        return {"deleted": True}

    @app.post("/api/reviews")
    async def review(template_id: str = Form(...), file: UploadFile = File(...)):
        path = await _save_upload(file)
        try:
            # The gate bounds parsing, rendering and optional model inference.
            async with review_slots:
                model = await run_in_threadpool(parse_document, path)
                engine = RuleEngine(str(rules_dir))
                if template_id.startswith("builtin:"):
                    rid = template_id.removeprefix("builtin:")
                    fmt = await run_in_threadpool(engine.check, path, rid, model=model)
                else:
                    template = store.get(template_id)
                    if template is None:
                        raise HTTPException(404, "模板不存在")
                    fmt = await run_in_threadpool(engine.check_custom, path, {
                        "meta": {"id": template_id, "name": template["name"]},
                        "rules": template["compiled_rules"],
                    }, model=model)
                typo = await run_in_threadpool(
                    run_typo_check, path, model=model,
                    use_llm=os.environ.get("DOCUMENT_CHECKER_USE_LLM") == "1")
                fmt_data, typo_data = fmt.to_dict(), typo.to_dict()
                review_id = str(uuid.uuid4())
                output_dir = review_dir / review_id
                try:
                    pages = await run_in_threadpool(render_docx, path, output_dir)
                    annotations = await run_in_threadpool(
                        map_findings, output_dir / "preview.pdf", model,
                        fmt_data["findings"], typo_data["findings"], pages)
                    preview = {
                        "status": "ready", "review_id": review_id,
                        "pdf_url": f"/api/reviews/{review_id}/preview.pdf",
                        "pages": [{
                            "number": page["number"],
                            "width_pt": page["width_pt"],
                            "height_pt": page["height_pt"],
                            "image_url": f"/api/reviews/{review_id}/pages/{page['number']}",
                        } for page in pages],
                        "annotations": annotations,
                        "unlocated_count": sum(a["precision"] == "unlocated"
                                               for a in annotations),
                    }
                except (PreviewError, OSError, ValueError, RuntimeError) as exc:
                    if output_dir.exists():
                        shutil.rmtree(output_dir)
                    preview = {"status": "failed", "reason": str(exc),
                               "pages": [], "annotations": []}
            return {"filename": file.filename, "template_id": template_id,
                    "format": fmt_data, "typo": typo_data,
                    "preview": preview,
                    "preview_status": preview["status"],
                    "repair_status": "待接入原 DOCX 定点修复"}
        except HTTPException:
            raise
        except (InvalidRuleError, ValueError, KeyError, OSError, RuntimeError) as exc:
            raise HTTPException(422, f"审查无法完成：{exc}") from exc
        finally:
            Path(path).unlink(missing_ok=True)

    return app


app = create_app()

