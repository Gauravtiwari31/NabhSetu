from __future__ import annotations

from urllib.parse import urlparse

from app.domain.models import SourceProfile


def url_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        return path
    return path


def path_is_blocked(url: str, blocked_paths: list[str] | tuple[str, ...]) -> str | None:
    path = url_path(url)
    lowered_url = url.lower()
    for rule in blocked_paths:
        if not rule or rule == "*":
            continue
        token = rule.strip()
        if token.startswith("http://") or token.startswith("https://"):
            if lowered_url.startswith(token.lower()):
                return token
            continue
        if not token.startswith("/"):
            token = "/" + token
        if path == token or path.startswith(token.rstrip("/") + "/") or path.startswith(token):
            return rule
    return None


def request_permitted(url: str, source: SourceProfile) -> tuple[bool, str | None]:
    blocked = path_is_blocked(url, source.policy.blocked_paths)
    if blocked:
        return False, blocked
    allowed = source.policy.allowed_paths or ["*"]
    if "*" in allowed:
        return True, None
    path = url_path(url)
    for rule in allowed:
        if path == rule or path.startswith(rule.rstrip("/") + "/") or path.startswith(rule):
            return True, None
    return False, "not-in-allowed-paths"
