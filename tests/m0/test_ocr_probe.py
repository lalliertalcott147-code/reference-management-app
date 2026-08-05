from probes.ocr_probe import run_probe


def test_ppocrv6_recognizes_fixed_english_text() -> None:
    texts = run_probe()
    assert any("catalyst" in text.lower() for text in texts)
