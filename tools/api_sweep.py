#!/usr/bin/env python
"""Exercise every API route and report status + payload shape."""
from __future__ import annotations
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from apix_api.main import app

PATHS = [
    "/health", "/dashboard/", "/docs", "/openapi.json",
    "/v1/index?frequency=daily", "/v1/index?frequency=weekly",
    "/v1/index?frequency=monthly", "/v1/index?variant=B", "/v1/index?variant=A",
    "/v1/index?basis=travel", "/v1/index?omega_preset=leisure_tilted",
    "/v1/index?format=csv&frequency=monthly",
    "/v1/index?format=sdmx-json&frequency=monthly",
    "/v1/index/apw/7", "/v1/index/apw/45",
    "/v1/index/routes/DEL-BOM?apw_days=7",
    "/v1/elasticity", "/v1/elasticity?route=DEL-BOM",
    "/v1/components", "/v1/availability", "/v1/availability?route=DEL-BOM",
    "/v1/availability/series?route=DEL-BOM&apw_days=7",
    "/v1/backtest", "/v1/backtest?base_year=2012", "/v1/backtest?basis=book",
    "/v1/cpi?base_year=2024", "/v1/cpi?base_year=2012",
    "/v1/coverage", "/v1/methodology",
]
c = TestClient(app)
ok = fail = 0
for p in PATHS:
    try:
        r = c.get(p)
        code = r.status_code
        n = len(r.content)
        print(f"{code}  {n:>8d}B  {p}")
        ok += (code == 200); fail += (code != 200)
    except Exception as e:
        print(f"ERR          -  {p}  {type(e).__name__}: {e}")
        fail += 1

# Negative cases: unknown ids must 404, not 500.
neg = [("/v1/index/routes/ZZZ-YYY", 404), ("/v1/provenance/not-a-real-id", 404),
       ("/v1/index/apw/999", 404), ("/v1/index?variant=Q", 422)]
print("\nnegative cases (must not 500):")
for p, want in neg:
    r = c.get(p)
    status = "OK" if r.status_code == want else f"got {r.status_code}, want {want}"
    print(f"{r.status_code}  {p}  -> {status}")
    ok += (r.status_code == want); fail += (r.status_code != want)

# Provenance round trip on a real published id.
iid = c.get("/v1/index?frequency=daily").json()["observations"][-1]["index_id"]
pr = c.get(f"/v1/provenance/{iid}")
print(f"\nprovenance round trip: {pr.status_code}  chain_intact="
      f"{pr.json()['hash_chain']['intact']}  quotes={pr.json()['quotes_behind_it']['n_quotes']}")
ok += (pr.status_code == 200); fail += (pr.status_code != 200)
print(f"\nTOTAL  ok={ok}  fail={fail}")
