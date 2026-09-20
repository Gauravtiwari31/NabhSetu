# Network egress

`NetworkEgressManager` sits under the router and above collector transports.
It exists for reliability, regional pinning, and worker distribution — not for
circumventing source controls.

```
Fare Query → Scheduler → Compliance Governor → Registry → Router
    → Network / Egress Policy → Direct / Fixed / Regional / Healthy Pool
    → Selected collector
```

## Modes

`DIRECT`, `STATIC_PROXY`, `PROXY_POOL`, `REGION_PINNED`, `FAILOVER`.

Demo default: `APIX_EGRESS_MODE=direct`. The system runs with no proxy
provider configured. Proxy credentials are environment/secret-manager
references on `egress_nodes.endpoint_reference`, never plaintext in the
database or logs.

## Rotation strategies (allowed)

`NONE`, `ROUND_ROBIN`, `HEALTH_BASED`, `LEAST_LOADED`, `REGION_PINNED`,
`SESSION_STICKY`.

There is no `ROTATE_ON_403`, `ROTATE_ON_CAPTCHA`, or `ROTATE_ON_BLOCK`.

## Failover rules

| Signal | Action |
|--------|--------|
| Dead proxy / TLS / timeout / unhealthy node | May select another healthy node |
| HTTP 429 | Back off; honour Retry-After; no egress change |
| HTTP 403 / CAPTCHA / robots / ban | Stop or review; no egress change |
| Sticky session | Same node until expiry or **explicit** session restart |

## Observability

Attempts record `egress_id`, region, `session_id`, latency, and HTTP category.
Metrics distinguish network failures from 429/403/CAPTCHA/source-block counts.
