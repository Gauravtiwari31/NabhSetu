from __future__ import annotations

import json
import re
from typing import Any

NEXT_DATA = re.compile(
    r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
JSON_LD = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
APP_JSON = re.compile(
    r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)

BLOCK_HINTS = (
    "access denied",
    "pardon our interruption",
    "your access has been blocked",
    "http 403",
    "error 403",
)
CHALLENGE_HINTS = (
    "cf-challenge",
    "cf-browser-verification",
    "are you a robot",
    "i'm not a robot",
    "complete the security check",
    "verify you are human",
    "checking your browser",
)


def looks_like_challenge(html: str) -> bool:
    lowered = html.lower()
    return any(token in lowered for token in CHALLENGE_HINTS)


def looks_like_block(html: str) -> bool:
    lowered = html.lower()
    return any(token in lowered for token in BLOCK_HINTS)


def _load_json(raw: str) -> Any | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def extract_embedded_json(html: str) -> list[Any]:
    blobs: list[Any] = []
    seen: set[int] = set()
    for pattern in (NEXT_DATA, JSON_LD, APP_JSON):
        for match in pattern.finditer(html):
            parsed = _load_json(match.group(1))
            if parsed is None:
                continue
            marker = id(parsed) if not isinstance(parsed, (dict, list)) else hash(json.dumps(parsed, sort_keys=True, default=str)[:4000])
            if marker in seen:
                continue
            seen.add(marker)
            blobs.append(parsed)
    return blobs
