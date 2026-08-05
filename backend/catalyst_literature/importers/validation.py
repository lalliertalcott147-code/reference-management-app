from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .models import ImportValidationError

MAX_IMPORT_BYTES = 25 * 1024 * 1024
MAX_XLSX_EXPANDED_BYTES = 100 * 1024 * 1024


def detect_format(filename: str, data: bytes) -> str:
    if not data:
        raise ImportValidationError("The selected export file is empty")
    if len(data) > MAX_IMPORT_BYTES:
        raise ImportValidationError("The selected export exceeds the 25 MB limit")
    if data.startswith(b"PK\x03\x04"):
        _validate_xlsx_archive(data)
        return "xlsx"
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise ImportValidationError("Legacy .xls files are not supported; export as .xlsx")
    text = decode_text(data)
    first_lines = [line.strip() for line in text.splitlines()[:20] if line.strip()]
    if any(line.startswith("TY  - ") for line in first_lines):
        return "ris"
    if any(line.startswith(("FN ", "VR ", "PT ")) for line in first_lines):
        return "wos_plain_text"
    suffix = Path(filename).suffix.lower()
    raise ImportValidationError(
        f"The file content is not a supported WoS Plain Text, RIS, or Excel export ({suffix})"
    )


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportValidationError("The text export encoding could not be decoded safely")


def _validate_xlsx_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or not any(
                name.startswith("xl/worksheets/") for name in names
            ):
                raise ImportValidationError("The ZIP file is not a valid .xlsx workbook")
            expanded = sum(item.file_size for item in archive.infolist())
            if expanded > MAX_XLSX_EXPANDED_BYTES:
                raise ImportValidationError("The expanded workbook exceeds the safe size limit")
            for item in archive.infolist():
                if item.compress_size and item.file_size / item.compress_size > 200:
                    raise ImportValidationError("The workbook has an unsafe compression ratio")
                if item.filename.lower().endswith(("vbaproject.bin", ".exe", ".dll")):
                    raise ImportValidationError(
                        "The workbook contains unsupported executable content"
                    )
    except zipfile.BadZipFile as error:
        raise ImportValidationError("The Excel export is damaged") from error
