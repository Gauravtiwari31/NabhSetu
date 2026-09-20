from __future__ import annotations

from decimal import Decimal

from app.acquisition.discovery.robots import RobotsSnapshot
from app.acquisition.http import FetchedPage
from app.config import Settings
from app.domain.enums import (
    CollectionStatus,
    CollectorModality,
    HttpResponseCategory,
    NetworkFailureCategory,
)
from app.domain.hashing import sha256_hex
from app.domain.models import (
    CollectionError,
    CollectionResult,
    PayloadReference,
    SourceProfile,
    utcnow,
)
from app.sources.common.fare_extract import ParseOutcome
from app.sources.common.html import looks_like_block, looks_like_challenge


def confidence_for(settings: Settings, collector: CollectorModality) -> Decimal:
    mapping = {
        CollectorModality.PUBLIC_API: settings.confidence_public_api,
        CollectorModality.STRUCTURED_FEED: settings.confidence_structured_feed,
        CollectorModality.STATIC_HTML: settings.confidence_static_html,
        CollectorModality.EMBEDDED_JSON: settings.confidence_embedded_json,
        CollectorModality.PLAYWRIGHT_NETWORK: settings.confidence_playwright_network,
        CollectorModality.PLAYWRIGHT_DOM: settings.confidence_playwright_dom,
        CollectorModality.DOCUMENT: settings.confidence_document,
        CollectorModality.VISUAL: settings.confidence_visual,
        CollectorModality.MOCK: settings.confidence_mock,
    }
    return mapping[collector]


def payload_ref(body: str | bytes, media_type: str, method: str, limit: int) -> PayloadReference:
    if isinstance(body, str):
        data = body.encode("utf-8")
    else:
        data = body
    clipped = data[:limit]
    return PayloadReference(
        content_hash=sha256_hex(clipped),
        media_type=media_type,
        byte_size=len(clipped),
        capture_method=method,
    )


def denied_result(
    source: SourceProfile,
    collector: CollectorModality,
    started,
    *,
    code: str,
    message: str,
    status: CollectionStatus = CollectionStatus.POLICY_DENIED,
    http_status: int | None = None,
    extra: dict | None = None,
) -> CollectionResult:
    metadata = extra or {}
    if http_status is not None:
        metadata["http_status"] = http_status
    return CollectionResult(
        source_id=source.id,
        collector=collector,
        status=status,
        requested_at=started,
        completed_at=utcnow(),
        errors=[CollectionError(code=code, message=message)],
        metadata=metadata,
        http_response_category=HttpResponseCategory.NONE,
        network_failure_category=NetworkFailureCategory.SOURCE_RESTRICTION,
    )


def from_page_error(
    source: SourceProfile,
    collector: CollectorModality,
    started,
    page: FetchedPage,
) -> CollectionResult | None:
    if page.collection_status is None:
        return None
    if page.collection_status == CollectionStatus.NO_RESULTS and page.status_code and page.status_code < 400:
        return None
    if looks_like_challenge(page.text):
        return CollectionResult(
            source_id=source.id,
            collector=collector,
            status=CollectionStatus.CAPTCHA_BLOCKED,
            requested_at=started,
            completed_at=utcnow(),
            errors=[CollectionError(code="CHALLENGE", message="Source presented a human-verification challenge")],
            metadata={"url": page.url, "http_status": page.status_code},
            http_response_category=page.http_response_category,
            network_failure_category=page.network_failure_category,
        )
    if looks_like_block(page.text) and page.status_code != 200:
        return CollectionResult(
            source_id=source.id,
            collector=collector,
            status=CollectionStatus.BLOCKED,
            requested_at=started,
            completed_at=utcnow(),
            errors=[CollectionError(code="BLOCKED", message="Source HTML indicates access denial")],
            metadata={"url": page.url, "http_status": page.status_code},
            http_response_category=page.http_response_category,
            network_failure_category=page.network_failure_category,
        )
    return CollectionResult(
        source_id=source.id,
        collector=collector,
        status=page.collection_status,
        requested_at=started,
        completed_at=utcnow(),
        errors=[
            CollectionError(
                code=page.collection_status.value.upper(),
                message=page.error or f"HTTP {page.status_code}",
                retryable=page.collection_status
                in {CollectionStatus.TEMPORARY_FAILURE, CollectionStatus.NETWORK_ERROR},
            )
        ],
        metadata={"url": page.url, "http_status": page.status_code},
        http_response_category=page.http_response_category,
        network_failure_category=page.network_failure_category,
    )


def from_outcome(
    source: SourceProfile,
    collector: CollectorModality,
    started,
    outcome: ParseOutcome,
    *,
    page: FetchedPage | None = None,
    parser_name: str,
    parser_version: str,
    limit: int,
) -> CollectionResult:
    body = page.text if page is not None else ""
    media = page.media_type if page is not None else "application/json"
    reference = payload_ref(body, media, collector.value, limit) if body else None
    return CollectionResult(
        source_id=source.id,
        collector=collector,
        status=outcome.status,
        requested_at=started,
        completed_at=utcnow(),
        raw_payload_reference=reference,
        payload_hash=reference.content_hash if reference else None,
        parser_name=parser_name,
        parser_version=parser_version,
        observations=outcome.observations,
        errors=(
            [CollectionError(code=outcome.status.value.upper(), message=outcome.message)]
            if outcome.message and outcome.status != CollectionStatus.SUCCESS
            else []
        ),
        metadata={"url": page.url if page else None, "http_status": page.status_code if page else None},
        http_response_category=page.http_response_category if page else HttpResponseCategory.NONE,
    )


def robots_or_deny(
    source: SourceProfile,
    collector: CollectorModality,
    started,
    robots: RobotsSnapshot | None,
) -> CollectionResult | None:
    if robots is None:
        return denied_result(
            source,
            collector,
            started,
            code="ROBOTS_MISSING",
            message="No robots snapshot is attached for this live collection",
        )
    if robots.status.value in {"unknown", "unreadable"}:
        return denied_result(
            source,
            collector,
            started,
            code="ROBOTS_UNREADABLE",
            message=robots.error or "robots.txt could not be read",
        )
    return None
