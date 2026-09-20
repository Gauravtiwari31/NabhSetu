"""Shared acquisition and fare-observation enumerations."""

from enum import StrEnum


class CollectorModality(StrEnum):
    PUBLIC_API = "public_api"
    STRUCTURED_FEED = "structured_feed"
    STATIC_HTML = "static_html"
    EMBEDDED_JSON = "embedded_json"
    PLAYWRIGHT_NETWORK = "playwright_network"
    PLAYWRIGHT_DOM = "playwright_dom"
    DOCUMENT = "document"
    VISUAL = "visual"
    MOCK = "mock"


class CollectionStatus(StrEnum):
    SUCCESS = "success"
    NO_RESULTS = "no_results"
    TEMPORARY_FAILURE = "temporary_failure"
    NETWORK_ERROR = "network_error"
    PARSER_ERROR = "parser_error"
    SOURCE_CHANGED = "source_changed"
    RATE_LIMITED = "rate_limited"
    BLOCKED = "blocked"
    CAPTCHA_BLOCKED = "captcha_blocked"
    POLICY_DENIED = "policy_denied"
    UNSUPPORTED = "unsupported"
    INVALID_DATA = "invalid_data"


class ComplianceDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REVIEW_REQUIRED = "review_required"


class AvailabilityState(StrEnum):
    AVAILABLE = "available"
    LIMITED = "limited"
    SOLD_OUT = "sold_out"
    UNKNOWN = "unknown"


class ValidationDisposition(StrEnum):
    VALID = "valid"
    FLAGGED = "flagged"
    EXCLUDED = "excluded"


class PublicationDisposition(StrEnum):
    ACCEPTED = "accepted"
    WINSORISED = "winsorised"
    QUARANTINED = "quarantined"
    EXCLUDED = "excluded"


class IndexFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class IndexBasis(StrEnum):
    BOOK = "book"
    TRAVEL = "travel"


class IndexVariant(StrEnum):
    T = "T"
    B = "B"
    A = "A"


class IndexRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BacktestStatus(StrEnum):
    REPORTABLE = "reportable"
    NOT_REPORTABLE = "not_reportable"
    UNAVAILABLE = "unavailable"


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class EgressMode(StrEnum):
    DIRECT = "direct"
    STATIC_PROXY = "static_proxy"
    PROXY_POOL = "proxy_pool"
    REGION_PINNED = "region_pinned"
    FAILOVER = "failover"


class RotationStrategy(StrEnum):
    NONE = "none"
    ROUND_ROBIN = "round_robin"
    HEALTH_BASED = "health_based"
    LEAST_LOADED = "least_loaded"
    REGION_PINNED = "region_pinned"
    SESSION_STICKY = "session_sticky"


class NetworkFailureCategory(StrEnum):
    NONE = "none"
    EGRESS_UNHEALTHY = "egress_unhealthy"
    DEAD_PROXY = "dead_proxy"
    CONNECTION_TIMEOUT = "connection_timeout"
    TLS_FAILURE = "tls_failure"
    PROXY_INFRASTRUCTURE = "proxy_infrastructure"
    SOURCE_RESTRICTION = "source_restriction"


class SourceType(StrEnum):
    AIRLINE = "airline"
    OTA = "ota"
    GOVERNMENT = "government"
    LICENSED_API = "licensed_api"
    MOCK = "mock"


class ReviewStatus(StrEnum):
    UNKNOWN = "unknown"
    APPROVED = "approved"
    DENIED = "denied"
    STALE = "stale"
    REVIEW_REQUIRED = "review_required"


class RobotsStatus(StrEnum):
    UNKNOWN = "unknown"
    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    UNREADABLE = "unreadable"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    DENIED = "denied"
    FAILED = "failed"


class HttpResponseCategory(StrEnum):
    NONE = "none"
    HTTP_2XX = "http_2xx"
    HTTP_429 = "http_429"
    HTTP_403 = "http_403"
    HTTP_4XX = "http_4xx"
    HTTP_5XX = "http_5xx"
    NETWORK = "network"
    SIMULATED = "simulated"


DEFAULT_COLLECTOR_PRIORITY: tuple[CollectorModality, ...] = (
    CollectorModality.PUBLIC_API,
    CollectorModality.STRUCTURED_FEED,
    CollectorModality.STATIC_HTML,
    CollectorModality.EMBEDDED_JSON,
    CollectorModality.PLAYWRIGHT_NETWORK,
    CollectorModality.PLAYWRIGHT_DOM,
    CollectorModality.DOCUMENT,
    CollectorModality.VISUAL,
    CollectorModality.MOCK,
)

STOP_STATUSES: frozenset[CollectionStatus] = frozenset(
    {
        CollectionStatus.BLOCKED,
        CollectionStatus.CAPTCHA_BLOCKED,
        CollectionStatus.POLICY_DENIED,
        CollectionStatus.SOURCE_CHANGED,
    }
)

FALLBACK_STATUSES: frozenset[CollectionStatus] = frozenset(
    {
        CollectionStatus.UNSUPPORTED,
        CollectionStatus.NO_RESULTS,
        CollectionStatus.PARSER_ERROR,
        CollectionStatus.INVALID_DATA,
    }
)

# Empty or inapplicable modalities must not open the circuit or consume retries.
NEUTRAL_STATUSES: frozenset[CollectionStatus] = frozenset(
    {
        CollectionStatus.UNSUPPORTED,
        CollectionStatus.NO_RESULTS,
    }
)

RETRY_STATUSES: frozenset[CollectionStatus] = frozenset(
    {
        CollectionStatus.TEMPORARY_FAILURE,
        CollectionStatus.NETWORK_ERROR,
        CollectionStatus.RATE_LIMITED,
    }
)

ALLOWED_LEAD_TIMES: tuple[int, ...] = (1, 7, 15, 30, 45)

EGRESS_FAILOVER_CATEGORIES: frozenset[NetworkFailureCategory] = frozenset(
    {
        NetworkFailureCategory.EGRESS_UNHEALTHY,
        NetworkFailureCategory.DEAD_PROXY,
        NetworkFailureCategory.CONNECTION_TIMEOUT,
        NetworkFailureCategory.TLS_FAILURE,
        NetworkFailureCategory.PROXY_INFRASTRUCTURE,
    }
)
