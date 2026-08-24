#!/usr/bin/env python
"""Validate the vectorised engine against an INDEPENDENT naive implementation.

The reference below is written straight from the Part 4 specification without
reference to the engine's internals. Agreeing with it is evidence the engine is
right; agreeing with itself would be evidence of nothing.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np, pandas as pd
from apix_index import compute, MethodConfig, WeightSet

KAPPA = ["route","carrier","apw_days","flight_number","fare_family","cabin","stops"]

def reference(q, w, omega, n_min=5):
    """Deliberately naive: nested Python loops, straight from the spec."""
    base = sorted(q["collected_date"].unique())[0]
    b = q[q["collected_date"] == base].set_index(KAPPA)["price"]
    lb = q[q["collected_date"] == base].groupby(
        ["route","carrier","apw_days","flight_number"])["price"].min()
    out = {}
    for period, pg in q.groupby("collected_date"):
        cells = {}
        for (r, c, a), g in pg.groupby(["route","carrier","apw_days"]):
            gi = g.set_index(KAPPA)["price"]
            common = gi.index.intersection(b.index)
            if len(common) < n_min:
                continue
            matched = 100*np.exp(np.mean(np.log(gi.loc[common].values)
                                         - np.log(b.loc[common].values)))
            ln = g.groupby(["route","carrier","apw_days","flight_number"])["price"].min()
            cf = ln.index.intersection(lb.index)
            laf = (100*np.exp(np.mean(np.log(ln.loc[cf].values) - np.log(lb.loc[cf].values)))
                   if len(cf) else np.nan)
            ref = q[(q.route==r)&(q.carrier==c)&(q.apw_days==a)].groupby(
                "collected_date")["fare_family"].nunique().max()
            A = min(max(g["fare_family"].nunique()/ref, 1e-6), 1.0)
            cells[(r, c, int(a))] = np.exp(A*np.log(matched) + (1-A)*np.log(laf))
        tot = ow = 0.0
        for a in sorted({k[2] for k in cells}):
            routes = sorted({k[0] for k in cells if k[2] == a})
            wr = {r: w.route_weights[r] for r in routes}; sw = sum(wr.values())
            acc = 0.0
            for r in routes:
                cs = sorted([k[1] for k in cells if k[0] == r and k[2] == a])
                phi = {c: w.carrier_weights[r][c] for c in cs}; sp = sum(phi.values())
                acc += (wr[r]/sw)*sum((phi[c]/sp)*cells[(r,c,a)] for c in cs)
            tot += omega[a]*acc; ow += omega[a]
        out[period] = tot/ow
    return pd.Series(out)

rng = np.random.default_rng(3); rows = []
routes = ["DEL-BOM","DEL-BLR","BOM-BLR"]; carriers = ["6E","AI"]; apws = [7,30]
fams = ["SAVER","ECOVALUE","FLEXI"]
base = pd.Timestamp("2026-07-01")
for d in range(12):
    day = base + pd.Timedelta(days=d)
    for r in routes:
        for c in carriers:
            for a in apws:
                # induce bucket closure so the availability path is exercised
                fl = fams if not (r == "DEL-BOM" and d in (4,5)) else fams[1:]
                for f_i in range(5):
                    for fam in fl:
                        p = 4200*(1+0.003*d)*(1+0.2*fams.index(fam))*(1+rng.normal(0,0.02))
                        rows.append(dict(collected_date=day.date().isoformat(),
                            departure_date=(day+pd.Timedelta(days=a)).date().isoformat(),
                            route=r, carrier=c, apw_days=a, flight_number=f"{c}-{200+f_i}",
                            fare_family=fam, cabin="economy", stops=0, price=round(p,2),
                            disposition="ACCEPTED"))
q = pd.DataFrame(rows)
w = WeightSet({r: v for r, v in zip(routes, [0.5,0.3,0.2])},
              {r: {"6E":0.7,"AI":0.3} for r in routes}, weights_version="validation")
omega = {7:0.5, 30:0.5}
eng = compute(q, w, MethodConfig(apw_windows=(7,30), omega=omega, bootstrap_draws=0,
                                 apply_dow_smoothing=False)).headline.set_index("period")["value"]
ref = reference(q, w, omega)
cmp = pd.DataFrame({"engine": eng, "reference": ref})
cmp["absdiff"] = (cmp.engine - cmp.reference).abs()
print(f"periods compared      {len(cmp)}")
print(f"quotes                {len(q)}")
print(f"availability exercised: min A across cells = "
      f"{compute(q,w,MethodConfig(apw_windows=(7,30),omega=omega,bootstrap_draws=0,apply_dow_smoothing=False)).cells.availability.min():.3f}")
print(f"max abs difference    {cmp.absdiff.max():.3e}")
print(f"VERDICT               {'IDENTICAL' if cmp.absdiff.max() < 1e-9 else 'MISMATCH'}")
