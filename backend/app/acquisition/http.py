from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.acquisition.discovery.robots import RobotsSnapshot
from app.acquisition.path_policy import request_permitted
from app.config import Settings
from app.domain.enums import CollectionStatus, HttpResponseCategory, NetworkFailureCategory
from app.domain.models import SourceProfile
from app.network_egress.classification import classify_http_status


@dataclass
class FetchedPage:
    url: str
    status_code: int | None
    media_type: str
    text: str
    content: bytes
    error: str | None = None
    collection_status: CollectionStatus | None = None
    http_response_category: HttpResponseCategory = HttpResponseCategory.NONE
    network_failure_category: NetworkFailureCategory = NetworkFailureCategory.NONE


class GovernedHttpClient:
    """Identified HTTP client. Refuses disallowed paths and does not spoof browsers."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport
        self._cache: dict[str, FetchedPage] = {}

    @property
    def user_agent(self) -> str:
        return self.settings.identified_user_agent

    def clear_cache(self) -> None:
        self._cache.clear()

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            self.settings.http_timeout_seconds,
            connect=self.settings.http_connect_timeout_seconds,
        )
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-IN,en;q=0.9",
        }
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
            transport=self.transport,
        )

    async def get(
        self,
        url: str,
        source: SourceProfile,
        *,
        robots: RobotsSnapshot | None,
        cache: bool = True,
    ) -> FetchedPage:
        if cache and url in self._cache:
            return self._cache[url]

        permitted, rule = request_permitted(url, source)
        if not permitted:
            page = FetchedPage(
                url=url,
                status_code=None,
                media_type="",
                text="",
                content=b"",
                error=f"blocked_path:{rule}",
                collection_status=CollectionStatus.POLICY_DENIED,
                http_response_category=HttpResponseCategory.NONE,
                network_failure_category=NetworkFailureCategory.SOURCE_RESTRICTION,
            )
            return page

        if robots is None or robots.status.value in {"unknown", "unreadable"}:
            page = FetchedPage(
                url=url,
                status_code=None,
                media_type="",
                text="",
                content=b"",
                error="robots_unread",
                collection_status=CollectionStatus.POLICY_DENIED,
                network_failure_category=NetworkFailureCategory.SOURCE_RESTRICTION,
            )
            return page
        if not robots.can_fetch(self.user_agent, url):
            page = FetchedPage(
                url=url,
                status_code=None,
                media_type="",
                text="",
                content=b"",
                error="robots_disallow",
                collection_status=CollectionStatus.POLICY_DENIED,
                network_failure_category=NetworkFailureCategory.SOURCE_RESTRICTION,
            )
            return page

        try:
            async with self._client() as client:
                response = await client.get(url)
        except httpx.TimeoutException as exc:
            page = FetchedPage(
                url=url,
                status_code=None,
                media_type="",
                text="",
                content=b"",
                error=type(exc).__name__,
                collection_status=CollectionStatus.NETWORK_ERROR,
                http_response_category=HttpResponseCategory.NETWORK,
                network_failure_category=NetworkFailureCategory.CONNECTION_TIMEOUT,
            )
            return page
        except httpx.TransportError as exc:
            category = NetworkFailureCategory.TLS_FAILURE if "ssl" in type(exc).__name__.lower() else NetworkFailureCategory.CONNECTION_TIMEOUT
            page = FetchedPage(
                url=url,
                status_code=None,
                media_type="",
                text="",
                content=b"",
                error=type(exc).__name__,
                collection_status=CollectionStatus.NETWORK_ERROR,
                http_response_category=HttpResponseCategory.NETWORK,
                network_failure_category=category,
            )
            return page

        media_type = response.headers.get("content-type", "")
        page = FetchedPage(
            url=str(response.url),
            status_code=response.status_code,
            media_type=media_type,
            text=response.text,
            content=response.content,
            http_response_category=classify_http_status(response.status_code),
        )
        if response.status_code == 403:
            page.collection_status = CollectionStatus.BLOCKED
            page.network_failure_category = NetworkFailureCategory.SOURCE_RESTRICTION
        elif response.status_code == 429:
            page.collection_status = CollectionStatus.RATE_LIMITED
            page.network_failure_category = NetworkFailureCategory.SOURCE_RESTRICTION
        elif response.status_code >= 500:
            page.collection_status = CollectionStatus.TEMPORARY_FAILURE
        elif response.status_code >= 400:
            page.collection_status = CollectionStatus.NO_RESULTS
        if cache:
            self._cache[url] = page
        return page
