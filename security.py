from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from typing import Any

_PREFIX = "dpapi:"
_SENSITIVE_KEYS = {"password", "pwd", "token", "access_token", "refresh_token", "authorization", "cookie", "sign", "key", "param"}

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

def protect_secret(value: str) -> str:
    if not value or value.startswith(_PREFIX) or os.name != "nt":
        return value
    import base64
    source, source_buffer = _blob(value.encode("utf-8"))
    output = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), "TiShiNeng", None, None, None, 0, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return _PREFIX + base64.b64encode(ctypes.string_at(output.pbData, output.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)

def reveal_secret(value: str) -> str:
    if not value or not value.startswith(_PREFIX):
        return value
    import base64
    source, source_buffer = _blob(base64.b64decode(value[len(_PREFIX):]))
    output = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)

def _mask(value: Any) -> str:
    text = str(value)
    return "***" if len(text) <= 8 else f"{text[:4]}...{text[-4:]}"

def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (_mask(item) if str(key).lower() in _SENSITIVE_KEYS else redact(item)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value

def safe_json(value: Any) -> str:
    return json.dumps(redact(value), ensure_ascii=False, default=str)
