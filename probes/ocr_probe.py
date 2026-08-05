from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.preflight import configure_runtime_home

ROOT = Path(__file__).resolve().parents[1]


def make_probe_image(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (900, 180), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 64)
    draw.text((35, 45), "Catalyst 2026", fill="black", font=font)
    image.save(path)


def extract_texts(result: Any) -> list[str]:
    if hasattr(result, "json"):
        payload = result.json
        if callable(payload):
            payload = payload()
        if isinstance(payload, dict):
            data = payload.get("res", payload)
            texts = data.get("rec_texts", []) if isinstance(data, dict) else []
            return [str(text) for text in texts]
    if isinstance(result, dict):
        return [str(text) for text in result.get("rec_texts", [])]
    return []


def run_probe() -> list[str]:
    configure_runtime_home()
    # PaddleOCR 3.7.0 does not publish a PEP 561 marker or typing stubs.
    from paddleocr import PaddleOCR  # type: ignore[import-untyped]

    artifact_dir = ROOT / "tests" / "artifacts" / "ocr"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    image_path = artifact_dir / "catalyst-probe.png"
    make_probe_image(image_path)

    pipeline = PaddleOCR(
        ocr_version="PP-OCRv6",
        device="cpu",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
    )
    texts: list[str] = []
    for result in pipeline.predict(str(image_path)):
        texts.extend(extract_texts(result))
    return texts


def main() -> int:
    texts = run_probe()
    print("OCR texts:", texts)
    if not any("catalyst" in text.lower() for text in texts):
        raise RuntimeError("PP-OCRv6 did not recognize the fixed probe text")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
