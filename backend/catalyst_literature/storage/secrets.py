from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from typing import Any

import apsw

from .database import utc_now

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    return (
        DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))),
        buffer,
    )


def _crypt_function(name: str) -> tuple[ctypes.WinDLL, Any]:
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI is only available on Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    return crypt32, getattr(crypt32, name)


def protect_secret(plaintext: str) -> str:
    _crypt32, function = _crypt_function("CryptProtectData")
    input_blob, _input_buffer = _blob(plaintext.encode("utf-8"))
    entropy_blob, _entropy_buffer = _blob(b"CatalystLiterature/v1")
    output_blob = DataBlob()
    success = function(
        ctypes.byref(input_blob),
        "Catalyst Literature",
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        protected = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        ctypes.WinDLL("kernel32", use_last_error=True).LocalFree(output_blob.pbData)


def unprotect_secret(ciphertext: str) -> str:
    _crypt32, function = _crypt_function("CryptUnprotectData")
    input_blob, _input_buffer = _blob(base64.b64decode(ciphertext, validate=True))
    entropy_blob, _entropy_buffer = _blob(b"CatalystLiterature/v1")
    output_blob = DataBlob()
    success = function(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    finally:
        ctypes.WinDLL("kernel32", use_last_error=True).LocalFree(output_blob.pbData)


class SecretStore:
    def __init__(self, connection: apsw.Connection) -> None:
        self.connection = connection

    def save(self, name: str, plaintext: str) -> None:
        ciphertext = protect_secret(plaintext)
        self.connection.execute(
            """
            INSERT INTO secrets(name, ciphertext, updated_at) VALUES(?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                ciphertext=excluded.ciphertext, updated_at=excluded.updated_at
            """,
            (name, ciphertext, utc_now()),
        )

    def read(self, name: str) -> str | None:
        row = self.connection.execute(
            "SELECT ciphertext FROM secrets WHERE name=?", (name,)
        ).fetchone()
        return None if row is None else unprotect_secret(str(row[0]))

    def masked(self, name: str) -> str | None:
        value = self.read(name)
        if value is None:
            return None
        suffix = value[-4:] if len(value) > 4 else value
        return f"****{suffix}"
