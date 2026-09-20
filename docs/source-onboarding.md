# Source onboarding

Each source is a plugin under `backend/app/sources/<name>/` with its own
`plugin.py`, `parser.py`, `normaliser.py`, `fixtures/`, and tests. Changing
source A must not require edits to source B or to the router.

## Checklist

1. Legal/terms review recorded on `sources.terms_review_status`.
2. robots.txt outcome recorded (`ALLOWED` / `DISALLOWED` / `UNREADABLE`).
   Unreadable fails closed.
3. Rate policy: minimum interval, concurrency, daily cap, allowed paths/routes.
4. Network policy: egress mode and whether a sticky session is required.
5. Capability flags and a **preferred adapter**. Do not enable every collector.
6. Parser fixtures: valid, missing-field, changed-layout, invalid-response.
7. Confidence is a configurable setting, not a universal statistical truth.

Discovery may **propose** capability changes with `REVIEW_REQUIRED`. It must
never set `automation_allowed=true` by itself.

## Live sources

Live airline plugins are registered in `backend/app/sources/catalog.py`; OTA
plugins live under `backend/app/sources/ota/`. robots.txt is fetched at
collection time and recorded on the source row. Discovery never sets
`automation_allowed=true` by itself. See `docs/ota-source-review.md` for the
current per-OTA terms decisions.

A local live run:

```
cd backend
APIX_DATA_MODE=live APIX_EGRESS_MODE=direct python scripts/live_collect.py
```

The runner persists only real outcomes: matching dated itineraries, or typed
failures (`NO_RESULTS`, `POLICY_DENIED`, `BLOCKED`, timeouts). It does not
invent fares.
