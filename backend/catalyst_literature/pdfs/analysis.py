from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

# pypdfium2 does not currently publish typing metadata.
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw  # type: ignore[import-untyped]

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")

OcrFunction = Callable[[Any, Path], tuple[str, list[dict[str, object]], float]]
ProgressFunction = Callable[[int, int], None]


class PdfAnalysisError(RuntimeError):
    pass


def inspect_pdf(path: Path) -> tuple[int, list[dict[str, object]]]:
    try:
        document = pdfium.PdfDocument(path)
    except Exception as error:
        raise PdfAnalysisError("PDF 已损坏、加密或无法读取") from error
    try:
        if len(document) < 1:
            raise PdfAnalysisError("PDF 没有页面")
        if len(document) > 5_000:
            raise PdfAnalysisError("PDF 页数超过 5000 页安全上限")
        pages: list[dict[str, object]] = []
        for index in range(min(len(document), 3)):
            page = document[index]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_range()
                finally:
                    text_page.close()
                pages.append({"page_number": index + 1, "text": text})
            finally:
                page.close()
        metadata = document.get_metadata_dict(skip_empty=True)
        candidates = extract_metadata_candidates(pages, metadata)
        return len(document), candidates
    finally:
        document.close()


def analyze_pdf(
    path: Path,
    runtime_home: Path,
    *,
    ocr: OcrFunction | None = None,
    cancel_file: Path | None = None,
    progress: ProgressFunction | None = None,
) -> dict[str, object]:
    try:
        document = pdfium.PdfDocument(path)
    except Exception as error:
        raise PdfAnalysisError("PDF 已损坏、加密或无法读取") from error
    pages: list[dict[str, object]] = []
    try:
        for index in range(len(document)):
            if cancel_file is not None and cancel_file.exists():
                raise InterruptedError("PDF 处理已取消")
            page = document[index]
            try:
                pages.append(_analyze_page(page, index + 1, runtime_home, ocr))
                if progress is not None:
                    progress(index + 1, len(document))
            finally:
                page.close()
        metadata = document.get_metadata_dict(skip_empty=True)
    finally:
        document.close()
    candidates = extract_metadata_candidates(pages[:3], metadata)
    return {"pages": pages, "candidates": candidates}


def _analyze_page(
    page: Any,
    page_number: int,
    runtime_home: Path,
    ocr: OcrFunction | None,
) -> dict[str, object]:
    width, height = (float(value) for value in page.get_size())
    text_page = page.get_textpage()
    try:
        text = str(text_page.get_text_range())
        blocks = _text_blocks(text_page, width, height)
    finally:
        text_page.close()
    printable = len("".join(text.split()))
    image_ratio = _image_ratio(page, width, height)
    if printable >= 80 or (printable >= 30 and image_ratio < 0.75):
        classification = "text"
    elif printable < 30 and image_ratio >= 0.45:
        classification = "scanned"
    else:
        classification = "review"
    source = "text" if printable else "none"
    confidence = 0.99 if classification == "text" else 0.35
    if classification == "scanned":
        ocr_function = ocr or paddle_ocr
        bitmap = page.render(scale=2.0)
        try:
            image = bitmap.to_pil()
        finally:
            bitmap.close()
        text, blocks, confidence = ocr_function(image, runtime_home)
        source = "ocr" if text.strip() else "none"
    return {
        "page_number": page_number,
        "width": width,
        "height": height,
        "classification": classification,
        "source": source,
        "text": text,
        "blocks": blocks,
        "confidence": confidence,
        "image_ratio": image_ratio,
    }


def _text_blocks(text_page: Any, width: float, height: float) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for index in range(int(text_page.count_rects())):
        left, bottom, right, top = (float(value) for value in text_page.get_rect(index))
        content = str(text_page.get_text_bounded(left, bottom, right, top)).strip()
        if content:
            blocks.append(
                {
                    "text": content,
                    "rect": [left / width, 1 - top / height, right / width, 1 - bottom / height],
                }
            )
    return blocks


def _image_ratio(page: Any, width: float, height: float) -> float:
    area = 0.0
    for image in page.get_objects(filter=(pdfium_raw.FPDF_PAGEOBJ_IMAGE,)):
        left, bottom, right, top = (float(value) for value in image.get_bounds())
        area += max(0.0, right - left) * max(0.0, top - bottom)
    return min(1.0, area / max(1.0, width * height))


def configure_ocr_environment(runtime_home: Path) -> None:
    import os

    runtime_home.mkdir(parents=True, exist_ok=True)
    paddlex_home = runtime_home / "paddlex"
    paddle_home = runtime_home / "paddle"
    paddlex_home.mkdir(parents=True, exist_ok=True)
    paddle_home.mkdir(parents=True, exist_ok=True)
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(paddlex_home.resolve())
    os.environ["PADDLE_HOME"] = str(paddle_home.resolve())


def paddle_ocr(image: Any, runtime_home: Path) -> tuple[str, list[dict[str, object]], float]:
    configure_ocr_environment(runtime_home)
    from paddleocr import PaddleOCR

    pipeline = PaddleOCR(
        ocr_version="PP-OCRv6",
        device="cpu",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
    )
    texts: list[str] = []
    blocks: list[dict[str, object]] = []
    scores: list[float] = []
    for result in pipeline.predict(image):
        payload = result.json() if callable(getattr(result, "json", None)) else result.json
        data = payload.get("res", payload) if isinstance(payload, dict) else {}
        rec_texts = data.get("rec_texts", [])
        rec_scores = data.get("rec_scores", [])
        rec_polys = data.get("rec_polys", [])
        for index, value in enumerate(rec_texts):
            text = str(value).strip()
            if not text:
                continue
            score = float(rec_scores[index]) if index < len(rec_scores) else 0.5
            polygon = rec_polys[index] if index < len(rec_polys) else []
            image_width, image_height = image.size
            points = [
                [float(point[0]) / image_width, float(point[1]) / image_height]
                for point in polygon
            ]
            texts.append(text)
            scores.append(score)
            blocks.append({"text": text, "polygon": points, "confidence": score})
    confidence = sum(scores) / len(scores) if scores else 0.0
    return "\n".join(texts), blocks, confidence


def extract_metadata_candidates(
    pages: list[dict[str, object]], metadata: dict[str, str]
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    title = metadata.get("Title", "").strip()
    first_text = str(pages[0].get("text", "")) if pages else ""
    lines = [" ".join(line.split()) for line in first_text.splitlines() if line.strip()]
    if title:
        candidates.append(_candidate("title", title, 0, title, "metadata", 0.85))
    elif lines:
        plausible = next(
            (line for line in lines if len(line) >= 12 and not DOI_PATTERN.search(line)),
            "",
        )
        if plausible:
            candidates.append(_candidate("title", plausible, 1, plausible, "text", 0.65))
    combined = "\n".join(str(page.get("text", "")) for page in pages)
    doi = DOI_PATTERN.search(combined)
    if doi:
        value = doi.group(0).rstrip(".,;)")
        candidates.append(_candidate("doi", value.lower(), 1, doi.group(0), "text", 0.95))
    abstract = re.search(
        r"\bAbstract\b\s*[:.-]?\s*(.{40,4000}?)(?=\n\s*(?:Keywords?|Introduction|1\.?\s))",
        combined,
        re.IGNORECASE | re.DOTALL,
    )
    if abstract:
        value = " ".join(abstract.group(1).split())
        candidates.append(_candidate("abstract", value, 1, value[:240], "text", 0.8))
    year = YEAR_PATTERN.search(combined[:3_000])
    if year:
        candidates.append(_candidate("year", year.group(0), 1, year.group(0), "text", 0.55))
    if len(lines) > 1 and len(lines[1]) < 300:
        candidates.append(_candidate("authors", lines[1], 1, lines[1], "text", 0.45))
    return candidates


def _candidate(
    field: str,
    value: str,
    page: int,
    evidence: str,
    method: str,
    confidence: float,
) -> dict[str, object]:
    return {
        "field_name": field,
        "value": value,
        "page_number": page,
        "evidence": evidence,
        "method": method,
        "confidence": confidence,
    }
