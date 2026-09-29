"""DOCX page preview renderer and PDF coordinate mapping."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

import pymupdf as fitz

MAX_PAGES = 200
IMAGE_SCALE = 1.5


class PreviewError(RuntimeError):
    pass


def _soffice() -> str:
    configured = os.environ.get("DOCUMENT_CHECKER_SOFFICE")
    if configured:
        if Path(configured).is_file():
            return configured
        raise PreviewError(f"渲染器不存在：{configured}")
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    local_console = (Path(__file__).resolve().parents[2] / "data" / "tools"
                     / "lo-unpacked" / "SourceDir" / "LibreOffice" / "program"
                     / "soffice.com")
    if local_console.is_file():
        return str(local_console)
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA")):
        if root:
            for name in ("LibreOffice/program/soffice.exe",
                         "Programs/LibreOffice/program/soffice.exe"):
                candidate = Path(root) / name
                if candidate.is_file():
                    return str(candidate)
    raise PreviewError("未找到 LibreOffice；请安装后设置 DOCUMENT_CHECKER_SOFFICE")


def render_docx(path: str | Path, output_dir: Path) -> list[dict]:
    """Convert with LibreOffice, then rasterize the same PDF used for geometry."""
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / "preview.pdf"
    with tempfile.TemporaryDirectory(prefix="doc-check-lo-") as profile:
        command = [_soffice(), "-env:UserInstallation=" + Path(profile).as_uri(),
                   "--headless", "--convert-to", "pdf:writer_pdf_Export",
                   "--outdir", str(output_dir), str(path)]
        try:
            run = subprocess.run(command, capture_output=True, text=True, timeout=90,
                                 check=False)
        except subprocess.TimeoutExpired as exc:
            raise PreviewError("DOCX 渲染超时（90 秒）") from exc
    converted = output_dir / (Path(path).stem + ".pdf")
    if run.returncode != 0 or not converted.is_file():
        detail = (run.stderr or run.stdout or "").strip()[-300:]
        raise PreviewError(f"DOCX 渲染失败：{detail or '未生成 PDF'}")
    converted.replace(pdf_path)
    try:
        with fitz.open(pdf_path) as pdf:
            if not 1 <= len(pdf) <= MAX_PAGES:
                raise PreviewError(f"页数超出预览范围（1–{MAX_PAGES} 页）")
            pages = []
            for index, page in enumerate(pdf, 1):
                image_name = f"page-{index}.png"
                page.get_pixmap(matrix=fitz.Matrix(IMAGE_SCALE, IMAGE_SCALE),
                                alpha=False).save(output_dir / image_name)
                pages.append({"number": index, "width_pt": round(page.rect.width, 2),
                              "height_pt": round(page.rect.height, 2),
                              "image_name": image_name})
            return pages
    except Exception as exc:
        if isinstance(exc, PreviewError):
            raise
        raise PreviewError(f"PDF 页面读取失败：{exc}") from exc


def _norm(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value) if not c.isspace())


def _pdf_chars(pdf_path: Path) -> tuple[str, list[dict]]:
    all_chars = []
    stream = []
    with fitz.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf, 1):
            raw = page.get_text("rawdict")
            for block in raw["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        for char in span["chars"]:
                            for letter in _norm(char.get("c", "")):
                                stream.append(letter)
                                all_chars.append({
                                    "page": page_number,
                                    "bbox": tuple(char["bbox"]),
                                })
    return "".join(stream), all_chars


def _rectangles(chars: list[dict], start: int, end: int) -> list[dict]:
    # One highlight per rendered line.
    rectangles = []
    for char in chars[start:end]:
        x0, y0, x1, y1 = char["bbox"]
        if rectangles and rectangles[-1]["page"] == char["page"] and abs(
                rectangles[-1]["y"] - y0) < 3 and x0 - (
                    rectangles[-1]["x"] + rectangles[-1]["width"]) < 12:
            rect = rectangles[-1]
            right = max(rect["x"] + rect["width"], x1)
            bottom = max(rect["y"] + rect["height"], y1)
            rect["width"] = round(right - rect["x"], 2)
            rect["height"] = round(bottom - rect["y"], 2)
        else:
            rectangles.append({"page": char["page"], "x": round(x0, 2),
                               "y": round(y0, 2), "width": round(x1-x0, 2),
                               "height": round(y1-y0, 2)})
    return rectangles


def map_findings(pdf_path: Path, model, format_findings: list[dict],
                 typo_findings: list[dict], pages: list[dict]) -> list[dict]:
    """Attach page geometry to findings; do not invent coordinates for misses."""
    stream, chars = _pdf_chars(pdf_path)
    paragraph_spans: dict[int, tuple[int, int]] = {}
    cursor = 0
    for index, paragraph in enumerate(model.paragraphs, 1):
        needle = _norm(paragraph.text)
        if not needle:
            continue
        pos = stream.find(needle, cursor)
        if pos >= 0:
            paragraph_spans[index] = (pos, pos + len(needle))
            cursor = pos + len(needle)

    annotations: list[dict] = []
    for i, finding in enumerate(format_findings):
        location = finding.get("location", "")
        match = re.match(r"第(\d+)段", location)
        item = {"id": f"format-{i}", "kind": "format", "finding_index": i,
                "location": location, "precision": "unlocated", "rects": []}
        if match:
            paragraph_index = int(match.group(1))
            span = paragraph_spans.get(paragraph_index)
            if span:
                start, end = span
                run_match = re.search(r"run\s*(\d+)", location)
                run_mapped = False
                if run_match:
                    run_number = int(run_match.group(1))
                    paragraph = model.paragraphs[paragraph_index - 1]
                    if (1 <= run_number <= len(paragraph.runs) and
                            paragraph.text == "".join(r.text for r in paragraph.runs)):
                        raw_start = sum(len(r.text) for r in paragraph.runs[:run_number - 1])
                        raw_end = raw_start + len(paragraph.runs[run_number - 1].text)
                        start = span[0] + len(_norm(paragraph.text[:raw_start]))
                        end = span[0] + len(_norm(paragraph.text[:raw_end]))
                        run_mapped = True
                item["rects"] = _rectangles(chars, start, end)
                if item["rects"]:
                    item["precision"] = "run" if run_mapped else "paragraph"
        elif location in {"页面设置", "全文", "文档开头", "文末", "页脚"} and pages:
            page = pages[-1] if location == "文末" else pages[0]
            item["rects"] = [{"page": page["number"], "x": 8, "y": 8,
                              "width": 16, "height": 16}]
            item["precision"] = "page"
        annotations.append(item)

    for i, finding in enumerate(typo_findings):
        item = {"id": f"typo-{i}", "kind": "typo", "finding_index": i,
                "location": f"第{finding.get('para_index')}段",
                "precision": "unlocated", "rects": []}
        para_index = finding.get("para_index")
        span = paragraph_spans.get(para_index)
        if span and isinstance(finding.get("sent_start"), int):
            paragraph = model.paragraphs[para_index - 1]
            offset = finding["sent_start"]
            original = finding.get("original", "")
            if paragraph.text[offset:offset + len(original)] == original:
                start = span[0] + len(_norm(paragraph.text[:offset]))
                end = start + len(_norm(original))
                item["rects"] = _rectangles(chars, start, end)
                if item["rects"]:
                    item["precision"] = "text"
        annotations.append(item)
    return annotations

