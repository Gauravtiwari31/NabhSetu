# Acquisition engine

Collectors share one result type so they are interchangeable.

## Flow

1. `QueryScheduler` can expand an observation date into T+1, T+7, T+15, T+30, T+45.
2. `ComplianceGovernor` evaluates the source **before** any adapter runs.
3. `SourceCapabilityRegistry` ranks compatible collectors:
   preferred adapter, last success, default modality order, circuit health, latency.
4. `NetworkEgressManager` issues an egress/session lease.
5. `AcquisitionRouter` executes bounded attempts.

## Collector contract

`BaseCollector.supports(source)` and `collect(query, source, lease=..., egress=...)`
return a `CollectionResult`. Unexpected exceptions are converted to
`TEMPORARY_FAILURE` at the router.

## Status handling

| Status | Router behaviour |
|--------|------------------|
| SUCCESS | Persist, update metrics, return |
| UNSUPPORTED / NO_RESULTS / PARSER_ERROR / INVALID_DATA | Try the next permitted adapter |
| TEMPORARY_FAILURE / NETWORK_ERROR | Bounded retry; egress failover only for network/infrastructure failure |
| RATE_LIMITED | Honour backoff / `Retry-After`; **do not** rotate egress |
| BLOCKED / CAPTCHA_BLOCKED / POLICY_DENIED / SOURCE_CHANGED | Stop this source; do not fallback inside it |

`NO_RESULTS` and `UNSUPPORTED` are circuit-neutral: they do not open the
breaker. That lets the waterfall keep probing later modalities and later dates.

Mock collector (`CollectorModality.MOCK`) is registered only when
`APIX_DATA_MODE=mock` and never performs network I/O.

## Default modality order

Public API → structured feed → static HTML → embedded JSON → Playwright
network → Playwright DOM → document → visual → mock.

A source profile may override this with `preferred_adapter` and learned success.
