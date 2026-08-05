from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from typing import Any

from .config import AppPaths
from .pdfs.analysis import configure_ocr_environment

REQUIRED_PACKAGED_MODULES = ("apsw", "pypdfium2", "paddle", "paddleocr")


def collect_runtime_probe(
    importer: Callable[[str], Any] = importlib.import_module,
) -> dict[str, object]:
    versions: dict[str, str] = {}
    loaded: dict[str, Any] = {}
    for module_name in REQUIRED_PACKAGED_MODULES:
        module = importer(module_name)
        loaded[module_name] = module
        versions[module_name] = str(getattr(module, "__version__", "unknown"))

    paddle = loaded["paddle"]
    tensor = paddle.to_tensor([1.0], dtype="float32")
    if tensor.numpy().tolist() != [1.0]:
        raise RuntimeError("Paddle CPU tensor self-check failed.")

    return {"ok": True, "modules": versions, "paddle_device": paddle.get_device()}


def main() -> int:
    paths = None
    try:
        paths = AppPaths.default()
        paths.ensure()
        configure_ocr_environment(paths.models / "ocr")
        result = collect_runtime_probe()
    except Exception as error:
        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if paths is not None:
        target = paths.runtime / "runtime-probe.json"
        temporary = target.with_suffix(".part")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(target)
    print(serialized)
    return 0 if result.get("ok") is True else 1
