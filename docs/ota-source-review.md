# OTA source review

Reviewed on 2026-09-20 for the SIH26056 research prototype. This is a
technical collection-policy review, not legal advice. The runtime still
fetches `robots.txt` before every live run and fails closed when it is
unreadable.

All live requests use the identified `Nabhsetu-Research-Bot/0.1` User-Agent,
direct egress, one source request at a time, and source-specific delays.
CAPTCHA, HTTP 403, and explicit access denial stop the source. The system does
not solve challenges, spoof fingerprints, replay undocumented APIs, or rotate
egress identities after rejection.

## MakeMyTrip

- Terms: `https://www.makemytrip.com/legal/in/eng/user_agreement.html`
- Decision: `DENIED`; `automation_allowed=false`.
- Evidence: the agreement expressly prohibits accessing, monitoring, or
  copying content with robots, spiders, scrapers, or other automated means
  without prior written permission.
- Live robots result: timed out and was recorded as `UNREADABLE`.

## Yatra

- Terms: `https://www.yatra.com/online/yatra-user-agreement.html`
- Decision: `REVIEW_REQUIRED`; `automation_allowed=false`.
- Evidence: the agreement prohibits obtaining information through means not
  intentionally made available, but the reviewed text does not provide clear
  research-automation permission.
- Live robots result: timed out and was recorded as `UNREADABLE`.

## EaseMyTrip

- Terms: `https://www.easemytrip.com/terms.html`
- Decision: `APPROVED` for anonymous public flight search only.
- Evidence: no explicit automated-access prohibition was found in the
  reviewed terms. The live `robots.txt` response was:
  `User-Agent: *` and `Allow: *`.
- Adapter: the Playwright collector operates the visible public form and
  extracts displayed `.nw_listing_bx` itinerary cards. It does not call an
  undocumented endpoint independently.

## Cleartrip

- Terms: `https://corporate.cleartrip.com/termsofuse.xhtml`
- Decision: `DENIED`; `automation_allowed=false`.
- Evidence: the terms expressly prohibit robots, spiders, scrapers, automated
  copying, and bypass of robots exclusions without written permission.
- Live robots result: readable, but flight-search and API paths are
  disallowed.

## ixigo

- Terms: `https://www.ixigo.com/about/terms-of-use/`
- Decision: `DENIED`; `automation_allowed=false`.
- Evidence: the terms prohibit automated or non-human access, data-mining
  tools, robots, spiders, scrapers, and offline readers.
- Live robots result: readable, with `/flights/search`, `/search/result/`, and
  `/api/` disallowed.

## Goibibo

- Terms: `https://www.goibibo.com/info/user-agreement/`
- Decision: `REVIEW_REQUIRED`; `automation_allowed=false`.
- Evidence: the accessible agreement did not clearly grant or deny automated
  research collection.
- Live robots result: timed out and was recorded as `UNREADABLE`.

## Reproduce the evidence

From `backend/`:

```text
python scripts/review_ota_policies.py
python scripts/live_collect_otas.py
```

The first command writes `data/ota-policy-review.json`. The second writes
`data/ota-live-run-report.json` and persists only real observations or typed
failure states.

## Latest live evidence

The 2026-09-20 direct-egress run covered DEL-BOM, DEL-BLR, and BOM-BLR at
T+1, T+7, T+15, T+30, and T+45:

- EaseMyTrip: 15 of 15 route/date cells succeeded, producing 1,823 real
  itinerary observations through the public form and DOM-card parser.
- MakeMyTrip, Yatra, Cleartrip, ixigo, and Goibibo: all 75 attempted cells
  were stopped as `POLICY_DENIED` before fare-page collection.
- Simulated observations: 0.
