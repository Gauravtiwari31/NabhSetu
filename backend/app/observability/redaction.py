from __future__ import annotations

from typing import Any

SECRET_HINTS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "token",
    "authorization",
    "proxy_password",
    "credential",
)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in SECRET_HINTS)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("***" if _is_secret_key(str(key)) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
