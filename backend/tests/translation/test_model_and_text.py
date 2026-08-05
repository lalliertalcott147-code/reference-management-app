from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from catalyst_literature.translation.model import ModelError, ModelInstaller, ModelManifest
from catalyst_literature.translation.text import protect_text, split_segments


def tiny_manifest(payload: bytes) -> ModelManifest:
    return ModelManifest(
        repository="official/test",
        filename="tiny.gguf",
        download_url="https://huggingface.co/official/test/resolve/main/tiny.gguf",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        version="test-v1",
        license="Apache-2.0",
    )


def test_model_install_is_explicit_atomic_and_hash_verified(tmp_path: Path) -> None:
    payload = b"GGUF-test-model"
    manifest = tiny_manifest(payload)
    installer = ModelInstaller(manifest, tmp_path, opener=lambda _url: io.BytesIO(payload))
    with pytest.raises(ModelError, match="明确确认"):
        installer.install(confirmed=False, progress=lambda _current, _total: None)
    progress: list[tuple[int, int]] = []
    installed = installer.install(confirmed=True, progress=lambda a, b: progress.append((a, b)))
    assert installed.read_bytes() == payload
    assert progress[-1] == (len(payload), len(payload))
    assert not installed.with_suffix(".gguf.part").exists()
    assert installer.status()["state"] == "ready"

    installed.write_bytes(b"corrupt")
    with pytest.raises(ModelError, match="大小不正确"):
        manifest.verify(installed)
    assert installer.status()["state"] == "invalid"


def test_failed_download_removes_partial_file(tmp_path: Path) -> None:
    payload = b"correct"
    installer = ModelInstaller(
        tiny_manifest(payload), tmp_path, opener=lambda _url: io.BytesIO(b"incorrect")
    )
    with pytest.raises(ModelError):
        installer.install(confirmed=True, progress=lambda _current, _total: None)
    assert list(tmp_path.glob("*.part")) == []
    assert list(tmp_path.glob("*.gguf")) == []


def test_protection_round_trip_preserves_scientific_tokens_and_user_terms() -> None:
    original = (
        "NiMo/Al2O3 catalyst gave 95 wt% conversion at 573 K "
        "(Smith et al., 2024) [12-14], DOI 10.1000/ABC.12, using ZSM-5."
    )
    protected = protect_text(original, ["ZSM-5"])
    assert "10.1000/ABC.12" not in protected.text
    assert "573 K" not in protected.text
    assert "ZSM-5" not in protected.text
    assert protected.restore(protected.text) == original
    with pytest.raises(ValueError, match="受保护内容"):
        protected.restore(protected.text.replace("⟦P0⟧", ""))


def test_segmentation_preserves_every_character_and_paragraph_boundary() -> None:
    original = "First sentence. Second sentence.\n\nThird paragraph has a conclusion."
    segments = split_segments(original, max_chars=40)
    assert "".join(segments) == original
    assert all(len(segment) <= 40 for segment in segments)
    assert "\n\n" in "".join(segments)
