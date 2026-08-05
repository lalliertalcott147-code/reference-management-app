# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

project = Path(SPECPATH)
datas = [
    (str(project / "frontend" / "dist"), "frontend/dist"),
    (str(project / "vendor" / "llama.cpp"), "vendor/llama.cpp"),
]
binaries = []
hiddenimports = [
    "catalyst_literature.pdfs.worker",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "paddle",
    "paddle.base.core",
    "paddle.framework",
    "paddle.inference",
]

for package in ("pypdfium2", "apsw"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# Collect Paddle's native runtime without recursively importing every optional
# distributed/TensorRT package; some of those plugins abort the probe process on CPU-only Windows.
datas += collect_data_files("paddle")
binaries += collect_dynamic_libs("paddle")
for package in ("paddleocr", "paddlex"):
    datas += collect_data_files(package)
hiddenimports += collect_submodules(
    "paddleocr",
    filter=lambda name: "._doc2md" not in name,
    on_error="ignore",
)
hiddenimports += collect_submodules(
    "paddlex",
    filter=lambda name: ".serving" not in name,
    on_error="ignore",
)

a = Analysis(
    [str(project / "backend" / "catalyst_literature" / "__main__.py")],
    pathex=[str(project / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib.tests", "numpy.tests"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CatalystLiterature",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CatalystLiterature",
)
