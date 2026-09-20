from __future__ import annotations

from app.domain.enums import (
    EGRESS_FAILOVER_CATEGORIES,
    CollectionStatus,
    HttpResponseCategory,
    NetworkFailureCategory,
)

RESTRICTION_STATUSES = {
    CollectionStatus.RATE_LIMITED,
    CollectionStatus.BLOCKED,
    CollectionStatus.CAPTCHA_BLOCKED,
    CollectionStatus.POLICY_DENIED,
}


def classify_http_status(status: int | None) -> HttpResponseCategory:
    if status is None:
        return HttpResponseCategory.NONE
    if 200 <= status < 300:
        return HttpResponseCategory.HTTP_2XX
    if status == 429:
        return HttpResponseCategory.HTTP_429
    if status == 403:
        return HttpResponseCategory.HTTP_403
    if 400 <= status < 500:
        return HttpResponseCategory.HTTP_4XX
    if status >= 500:
        return HttpResponseCategory.HTTP_5XX
    return HttpResponseCategory.NONE


def classify_collection_failure(
    status: CollectionStatus,
    *,
    http_status: int | None = None,
    network_category: NetworkFailureCategory = NetworkFailureCategory.NONE,
) -> NetworkFailureCategory:
    """Distinguish network/infrastructure failure from source access restriction."""
    if status in RESTRICTION_STATUSES:
        return NetworkFailureCategory.SOURCE_RESTRICTION
    if http_status in {401, 403, 429}:
        return NetworkFailureCategory.SOURCE_RESTRICTION
    if network_category in EGRESS_FAILOVER_CATEGORIES:
        return network_category
    if status == CollectionStatus.NETWORK_ERROR:
        return (
            network_category
            if network_category != NetworkFailureCategory.NONE
            else NetworkFailureCategory.CONNECTION_TIMEOUT
        )
    return NetworkFailureCategory.NONE


def may_failover_egress(category: NetworkFailureCategory) -> bool:
    return category in EGRESS_FAILOVER_CATEGORIES
