from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast
from urllib.request import urlopen


class ModelError(RuntimeError):
    """The configured local translation model is unavailable or invalid."""


@dataclass(frozen=True)
class ModelManifest:
    repository: str
    filename: str
    download_url: str
    size_bytes: int
    sha256: str
    version: str
    license: str

    def path_in(self, models_dir: Path) -> Path:
        return models_dir / self.filename

    def verify(self, path: Path) -> None:
        if not path.is_file():
            raise ModelError("翻译模型尚未安装")
        if path.stat().st_size != self.size_bytes:
            raise ModelError("翻译模型文件大小不正确, 请重新下载")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest().lower() != self.sha256.lower():
            raise ModelError("翻译模型完整性校验失败, 请删除后重新下载")


HY_MT2_Q4_K_M = ModelManifest(
    repository="tencent/Hy-MT2-1.8B-GGUF",
    filename="Hy-MT2-1.8B-Q4_K_M.gguf",
    download_url=(
        "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/main/"
        "Hy-MT2-1.8B-Q4_K_M.gguf"
    ),
    size_bytes=1_133_080_448,
    sha256="dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699",
    version="Hy-MT2-1.8B-Q4_K_M@b27182d",
    license="Apache-2.0",
)


def _open_url(url: str) -> BinaryIO:
    return cast(BinaryIO, urlopen(url, timeout=60))


class ModelInstaller:
    def __init__(
        self,
        manifest: ModelManifest,
        models_dir: Path,
        *,
        opener: Callable[[str], BinaryIO] = _open_url,
    ) -> None:
        if not manifest.download_url.startswith("https://huggingface.co/"):
            raise ValueError("Only the fixed official Hugging Face origin is allowed")
        self.manifest = manifest
        self.models_dir = models_dir
        self.opener = opener

    def status(self) -> dict[str, object]:
        path = self.manifest.path_in(self.models_dir)
        if not path.exists():
            state = "missing"
        else:
            try:
                self.manifest.verify(path)
            except ModelError:
                state = "invalid"
            else:
                state = "ready"
        return {
            "state": state,
            "repository": self.manifest.repository,
            "filename": self.manifest.filename,
            "size_bytes": self.manifest.size_bytes,
            "sha256": self.manifest.sha256,
            "license": self.manifest.license,
        }

    def install(self, *, confirmed: bool, progress: Callable[[int, int], None]) -> Path:
        if not confirmed:
            raise ModelError("下载 1.13 GB 模型前必须由用户明确确认")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        target = self.manifest.path_in(self.models_dir)
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.unlink(missing_ok=True)
        written = 0
        try:
            with closing(self.opener(self.manifest.download_url)) as source, temporary.open(
                "wb"
            ) as destination:
                for block in _blocks(source):
                    written += len(block)
                    if written > self.manifest.size_bytes:
                        raise ModelError("模型下载大小超过官方清单")
                    destination.write(block)
                    progress(written, self.manifest.size_bytes)
                destination.flush()
                os.fsync(destination.fileno())
            self.manifest.verify(temporary)
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return target


def _blocks(source: BinaryIO) -> Iterator[bytes]:
    while block := source.read(1024 * 1024):
        yield block
