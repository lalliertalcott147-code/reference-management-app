from __future__ import annotations

import hashlib
import io
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import AppPaths

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000
AVATAR_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


class AvatarError(ValueError):
    pass


@dataclass(frozen=True)
class AvatarFile:
    path: Path
    media_type: str


class AvatarStore:
    def __init__(self, paths: AppPaths) -> None:
        self.directory = paths.root / "profile"

    def current(self) -> AvatarFile | None:
        for extension, media_type in AVATAR_FORMATS.values():
            candidate = self.directory / f"avatar.{extension}"
            if candidate.is_file():
                return AvatarFile(candidate, media_type)
        return None

    def url(self) -> str | None:
        avatar = self.current()
        if avatar is None:
            return None
        stat = avatar.path.stat()
        version = f"{stat.st_mtime_ns:x}-{stat.st_size:x}"
        return f"/api/profile/avatar?v={version}"

    def save(self, content: bytes) -> AvatarFile:
        extension, media_type = self._validate(content)
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"avatar.{extension}"
        temporary = self.directory / f".avatar-{uuid.uuid4().hex}.part"
        try:
            with temporary.open("wb") as destination:
                destination.write(content)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

        for old_extension, _old_media_type in AVATAR_FORMATS.values():
            old_avatar = self.directory / f"avatar.{old_extension}"
            if old_avatar != target:
                old_avatar.unlink(missing_ok=True)
        return AvatarFile(target, media_type)

    @staticmethod
    def _validate(content: bytes) -> tuple[str, str]:
        if not content:
            raise AvatarError("头像文件不能为空")
        if len(content) > MAX_AVATAR_BYTES:
            raise AvatarError("头像文件不能超过 5 MB")
        try:
            with Image.open(io.BytesIO(content)) as image:
                image_format = image.format
                width, height = image.size
                if image_format not in AVATAR_FORMATS:
                    raise AvatarError("头像只支持 PNG、JPEG 或 WebP")
                if width < 1 or height < 1 or width * height > MAX_AVATAR_PIXELS:
                    raise AvatarError("头像像素尺寸过大")
                image.verify()
        except AvatarError:
            raise
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as error:
            raise AvatarError("头像不是有效的 PNG、JPEG 或 WebP 图片") from error
        extension, media_type = AVATAR_FORMATS[image_format]
        return extension, media_type

    def digest(self) -> str | None:
        avatar = self.current()
        if avatar is None:
            return None
        return hashlib.sha256(avatar.path.read_bytes()).hexdigest()
