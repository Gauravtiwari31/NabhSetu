from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.config import Settings
from app.domain.enums import RobotsStatus
from app.domain.models import utcnow


@dataclass
class RobotsSnapshot:
    status: RobotsStatus
    fetched_at: datetime
    robots_url: str
    body: str | None = None
    http_status: int | None = None
    error: str | None = None
    sitemaps: list[str] = field(default_factory=list)
    disallow_paths: list[str] = field(default_factory=list)
    parser: RobotFileParser | None = None

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if self.status != RobotsStatus.ALLOWED or self.parser is None:
            return False
        return bool(self.parser.can_fetch(user_agent, url))


def _looks_like_robots(body: str, content_type: str | None) -> bool:
    lowered_type = (content_type or "").lower()
    if "text/html" in lowered_type:
        return False
    stripped = body.lstrip()
    if stripped.lower().startswith("<!doctype") or stripped.lower().startswith("<html"):
        return False
    return "user-agent:" in body.lower() or "disallow:" in body.lower() or "sitemap:" in body.lower()


def _disallow_paths(body: str) -> list[str]:
    paths: list[str] = []
    applies = False
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            applies = agent == "*"
            continue
        if applies and line.lower().startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                paths.append(path)
    return paths


def _sitemaps(body: str, base_url: str) -> list[str]:
    found: list[str] = []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.lower().startswith("sitemap:"):
            target = line.split(":", 1)[1].strip()
            if target:
                found.append(urljoin(base_url, target))
    return found


def _wildcard_disallow_only(paths: list[str]) -> bool:
    tokens = {item.strip() for item in paths if item.strip()}
    return tokens == {"/"}


async def fetch_robots(settings: Settings, base_url: str) -> RobotsSnapshot:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    fetched_at = utcnow()
    timeout = httpx.Timeout(settings.http_timeout_seconds, connect=settings.http_connect_timeout_seconds)
    headers = {"User-Agent": settings.identified_user_agent, "Accept": "text/plain,*/*;q=0.1"}
    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=True, trust_env=False
        ) as client:
            response = await client.get(robots_url)
    except httpx.TimeoutException as exc:
        return RobotsSnapshot(
            status=RobotsStatus.UNREADABLE,
            fetched_at=fetched_at,
            robots_url=robots_url,
            error=f"timeout:{type(exc).__name__}",
        )
    except httpx.HTTPError as exc:
        return RobotsSnapshot(
            status=RobotsStatus.UNREADABLE,
            fetched_at=fetched_at,
            robots_url=robots_url,
            error=f"http:{type(exc).__name__}",
        )

    body = response.text
    if response.status_code >= 400 or not _looks_like_robots(body, response.headers.get("content-type")):
        return RobotsSnapshot(
            status=RobotsStatus.UNREADABLE,
            fetched_at=fetched_at,
            robots_url=robots_url,
            body=body[:4000],
            http_status=response.status_code,
            error="unreadable_robots",
        )

    parser = RobotFileParser()
    parser.parse(body.splitlines())
    disallows = _disallow_paths(body)
    status = RobotsStatus.DISALLOWED if _wildcard_disallow_only(disallows) else RobotsStatus.ALLOWED
    return RobotsSnapshot(
        status=status,
        fetched_at=fetched_at,
        robots_url=robots_url,
        body=body,
        http_status=response.status_code,
        sitemaps=_sitemaps(body, robots_url),
        disallow_paths=disallows,
        parser=parser,
    )
