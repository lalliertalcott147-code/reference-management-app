from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from catalyst_literature.pdfs.analysis import analyze_pdf, inspect_pdf
from PIL import Image, ImageDraw

from .helpers import write_text_pdf


def test_normal_pdf_extracts_text_boxes_and_metadata_candidates(tmp_path: Path) -> None:
    path = tmp_path / "normal.pdf"
    write_text_pdf(
        path,
        [
            "Selective Copper Catalyst for CO2 Hydrogenation",
            "Ming Li and Alex Smith",
            "Published 2026 DOI 10.1000/CAT.2026.1",
            "Abstract This catalyst gives excellent selectivity under mild conditions.",
            "Introduction",
        ],
    )
    page_count, candidates = inspect_pdf(path)
    assert page_count == 1
    assert any(item["field_name"] == "doi" for item in candidates)
    result = analyze_pdf(path, tmp_path / "runtime", ocr=lambda _image, _home: ("", [], 0))
    page = result["pages"][0]  # type: ignore[index]
    assert page["classification"] == "text"  # type: ignore[index]
    assert page["source"] == "text"  # type: ignore[index]
    assert "Copper Catalyst" in page["text"]  # type: ignore[index]
    assert page["blocks"]  # type: ignore[index]


def test_scanned_page_uses_ocr_only_for_that_page(tmp_path: Path) -> None:
    image = Image.new("RGB", (700, 900), "white")
    ImageDraw.Draw(image).text((50, 80), "Scanned catalyst", fill="black")
    path = tmp_path / "scan.pdf"
    image.save(path, "PDF", resolution=72)
    calls: list[int] = []

    def fake_ocr(_image: object, _home: Path) -> tuple[str, list[dict[str, object]], float]:
        calls.append(1)
        return "Scanned catalyst OCR", [{"text": "Scanned catalyst OCR"}], 0.91

    result = analyze_pdf(path, tmp_path / "runtime", ocr=fake_ocr)
    page = result["pages"][0]  # type: ignore[index]
    assert page["classification"] == "scanned"  # type: ignore[index]
    assert page["source"] == "ocr"  # type: ignore[index]
    assert page["confidence"] == 0.91  # type: ignore[index]
    assert calls == [1]


def test_mixed_pdf_keeps_text_page_and_ocrs_only_image_page(tmp_path: Path) -> None:
    text_pdf = tmp_path / "text.pdf"
    scan_pdf = tmp_path / "image.pdf"
    mixed_pdf = tmp_path / "mixed.pdf"
    write_text_pdf(text_pdf, ["Text layer catalyst " + "content " * 20])
    image = Image.new("RGB", (700, 900), "white")
    ImageDraw.Draw(image).text((50, 80), "Image-only page", fill="black")
    image.save(scan_pdf, "PDF", resolution=72)
    mixed = pdfium.PdfDocument.new()
    text_document = pdfium.PdfDocument(text_pdf)
    image_document = pdfium.PdfDocument(scan_pdf)
    try:
        mixed.import_pages(text_document)
        mixed.import_pages(image_document)
        mixed.save(mixed_pdf)
    finally:
        mixed.close()
        text_document.close()
        image_document.close()
    calls: list[int] = []

    def fake_ocr(_image: object, _home: Path) -> tuple[str, list[dict[str, object]], float]:
        calls.append(1)
        return "OCR image page", [], 0.9

    result = analyze_pdf(mixed_pdf, tmp_path / "runtime", ocr=fake_ocr)
    pages = result["pages"]
    assert pages[0]["source"] == "text"  # type: ignore[index]
    assert pages[1]["source"] == "ocr"  # type: ignore[index]
    assert calls == [1]
