"""Deterministic canonical JSON and SHA-256 helpers."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serialisable")


def canonical_dumps(value: Any) -> str:
    """Return stable JSON: sorted keys, no extra whitespace, Decimal as string."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_default, ensure_ascii=True)


def sha256_hex(value: str | bytes) -> str:
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_canonical(value: Any) -> str:
    return sha256_hex(canonical_dumps(value))


def chain_hash(previous: str, record: Any) -> str:
    """Tamper-evident hash: SHA256(previous || canonical(record))."""
    return sha256_hex(previous + canonical_dumps(record))
