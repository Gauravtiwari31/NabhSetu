# Compliance

Collection is fail-closed. Coverage is an optimisation target, not a reason to
bypass access controls.

## Governor decisions

- **ALLOW** — a short-lived lease is issued; rate capacity is reserved atomically.
- **DENY** — no collector runs. Includes disabled sources, robots disallowed,
  quota exhausted, CAPTCHA/block circuits, mock sources in live mode.
- **REVIEW_REQUIRED** — terms/robots review missing or stale. The router does
  not collect.

The router maps non-ALLOW outcomes to `POLICY_DENIED` for the job.

## Explicitly out of scope

The platform must not implement:

- CAPTCHA solving
- fingerprint spoofing or stealth-browser evasion
- authentication bypass or credential theft
- rate-limit circumvention
- automatic proxy switching to defeat blocks
- robots.txt circumvention
- retries after a source has explicitly rejected automated access

A test (`tests/test_no_circumvention.py`) fails CI if those capabilities appear
in `backend/app`.

## Captcha and blocks

```
CAPTCHA / 403 access denial
    -> source state = restricted
    -> audit event
    -> stop this source
    -> scheduler may choose a different independently permitted source
```

Never: CAPTCHA → solver → continue, or 403 → change IP → retry.
