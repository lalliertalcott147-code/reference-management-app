from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from catalyst_literature.pdfs.analysis import configure_ocr_environment
from catalyst_literature.runtime_probe import (
    REQUIRED_PACKAGED_MODULES,
    collect_runtime_probe,
    main,
)


class FakeTensor:
    def numpy(self) -> FakeTensor:
        return self

    def tolist(self) -> list[float]:
        return [1.0]


def test_runtime_probe_imports_every_packaged_native_dependency() -> None:
    imported: list[str] = []

    def importer(name: str) -> Any:
        imported.append(name)
        if name == "paddle":
            return SimpleNamespace(
                __version__="3.2.0",
                to_tensor=lambda *_args, **_kwargs: FakeTensor(),
                get_device=lambda: "cpu",
            )
        return SimpleNamespace(__version__="test")

    result = collect_runtime_probe(importer)

    assert imported == list(REQUIRED_PACKAGED_MODULES)
    assert result["ok"] is True
    assert result["paddle_device"] == "cpu"


def test_runtime_probe_fails_if_a_required_module_is_missing() -> None:
    def importer(name: str) -> Any:
        if name == "paddleocr":
            raise ModuleNotFoundError(name)
        if name == "paddle":
            return SimpleNamespace(
                __version__="3.2.0",
                to_tensor=lambda *_args, **_kwargs: FakeTensor(),
                get_device=lambda: "cpu",
            )
        return SimpleNamespace(__version__="test")

    with pytest.raises(ModuleNotFoundError, match="paddleocr"):
        collect_runtime_probe(importer)


def test_ocr_environment_uses_managed_model_directory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USERPROFILE", "unchanged-profile")
    configure_ocr_environment(tmp_path / "ocr")

    assert __import__("os").environ["USERPROFILE"] == "unchanged-profile"
    assert __import__("os").environ["PADDLE_PDX_CACHE_HOME"] == str(
        (tmp_path / "ocr" / "paddlex").resolve()
    )
    assert __import__("os").environ["PADDLE_HOME"] == str(
        (tmp_path / "ocr" / "paddle").resolve()
    )


def test_runtime_probe_writes_machine_readable_result(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CATALYST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        "catalyst_literature.runtime_probe.collect_runtime_probe",
        lambda: {"ok": True, "modules": {}, "paddle_device": "cpu"},
    )

    assert main() == 0
    result = (tmp_path / "data" / "runtime" / "runtime-probe.json").read_text(
        encoding="utf-8"
    )
    assert '"ok": true' in result
