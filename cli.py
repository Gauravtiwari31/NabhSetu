#!/usr/bin/env python
"""Nabhsetu command line.

    python cli.py init                       create the schema and seed dimensions
    python cli.py backfill --days 90         build a quote history (synthetic rung)
    python cli.py index                      compute and publish the index family
    python cli.py elasticity                 fit eta(tau) and report tau*
    python cli.py verify                     hash chain + quality contract
    python cli.py reproduce                  recompute and diff against published
    python cli.py status                     what is in the store
    python cli.py serve                      run the API and dashboard
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from apix_store import db  # noqa: E402

# The demo basket: the six sectors the PS names, both directions. The full
# 60-route basket stays configured in config/basket.yaml and is what the
# coverage ledger reports against -- so the demo's partial coverage is VISIBLE
# rather than quietly redefined as 100%.
DEMO_PAIRS = [("DEL", "BOM"), ("DEL", "BLR"), ("BOM", "BLR"),
              ("DEL", "CCU"), ("DEL", "MAA"), ("BLR", "HYD")]
DEMO_ROUTES = [f"{a}-{b}" for a, b in DEMO_PAIRS] + [f"{b}-{a}" for a, b in DEMO_PAIRS]


def _conn():
    return db.connect()


def cmd_init(args):
    cfg = db.load_config()
    conn = _conn()
    db.init_schema(conn)
    counts = db.seed_dimensions(conn, cfg)
    today = date.today()
    n_dates = db.seed_dim_date(conn, today - timedelta(days=400), today + timedelta(days=400))
    counts["dim_date"] = n_dates
    print(f"database: {db.db_path()}")
    for k, v in counts.items():
        print(f"  {k:24s} {v:>6d}")
    w = db.build_weights(conn, cfg)
    print(f"  weights_version          {w.weights_version}")
    print(f"  weight source            {w.source}")


def cmd_backfill(args):
    from apix_collect import runner
    cfg = db.load_config()
    conn = _conn()
    routes = None if args.all_routes else DEMO_ROUTES
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = end - timedelta(days=args.days - 1)
    print(f"backfilling {start} .. {end}  ({args.days} days, "
          f"{len(routes) if routes else 'all'} routes)")
    total = 0

    def progress(s):
        nonlocal total
        total += s["n_stored"]
        print(f"  {s['date']}  raw={s['n_raw']:>6d}  stored={s['n_stored']:>6d}  "
              f"{s['dispositions']}")

    summaries = runner.backfill(conn, cfg, start, end, routes=routes, progress=progress)
    print(f"\nstored {total} quotes over {len(summaries)} days")
    print("NOTE: every row is stamped is_synthetic=1. Charts drawn from this "
          "must be watermarked SYNTHETIC.")


def cmd_index(args):
    from apix_pipeline import run_index
    cfg = db.load_config()
    conn = _conn()
    weights = db.build_weights(conn, cfg)
    variants = args.variants.split(",") if args.variants else None
    presets = args.presets.split(",") if args.presets else None
    out = run_index.run(conn, cfg, weights, variants=variants, presets=presets,
                        bootstrap_draws=args.bootstrap,
                        enforce_quality=not args.ignore_quality)
    print(f"run_id            {out['run_id']}")
    print(f"index values      {out['n_index_values']}")
    print(f"quotes used       {out['n_quotes_publishable']}")
    print(f"method_version    {out['method_version']}")
    print(f"weights_version   {out['weights_version']}")
    print(f"synthetic         {out['is_synthetic']}")
    q = out["quality"]
    print(f"quality           {q['n_passed']}/{q['n_checks']} passed"
          + (f"  BLOCKING: {q['blocking']}" if q["blocking"] else "")
          + (f"  alerts: {q['alerts']}" if q["alerts"] else ""))
    key = f"Nabhsetu-{cfg['method']['headline_variant']}|book|{cfg['method']['default_omega_preset']}"
    res = out["results"].get(key)
    if res is not None:
        h = res.headline
        print(f"\nheadline {key}  ({len(h)} periods)")
        print(h[["period", "value", "se", "ci_low", "ci_high", "n_cells", "coverage_pct"]]
              .tail(10).to_string(index=False))
        print("\ndiagnostics:", json.dumps(res.diagnostics, indent=2, default=str))


def cmd_elasticity(args):
    from apix_pipeline import elasticity, run_index
    conn = _conn()
    quotes = run_index.attach_variant_prices(db.read_quotes(conn))
    fit = elasticity.fit(quotes, route=args.route)
    label = args.route or "all routes (pooled, with route FE)"
    print(f"lead-time elasticity surface -- {label}")
    print(f"  n_obs {fit.n_obs}   clusters(flights) {fit.n_clusters}   params {fit.n_params}")
    print(f"  b1 (ln tau)     {fit.beta1:+.5f}  (cluster SE {fit.se_beta1:.5f})")
    print(f"  b2 (ln tau)^2   {fit.beta2:+.5f}  (cluster SE {fit.se_beta2:.5f})")
    print(f"  R^2 {fit.r_squared:.4f}   adj {fit.adj_r_squared:.4f}")
    if fit.tau_star:
        ci = fit.tau_star_ci
        band = f"  95% CI [{ci[0]:.1f}, {ci[1]:.1f}]" if ci else ""
        print(f"\n  tau* = {fit.tau_star:.1f} days{band}")
        print(f"  -> cheapest time to book {args.route or 'on the basket'} "
              f"is about {fit.tau_star:.0f} days out")
    if fit.note:
        print(f"\n  NOTE: {fit.note}")
    print("\n  eta(tau):")
    for t in (1, 7, 15, 30, 45):
        print(f"    tau={t:>2d}  eta={float(fit.eta(t)):+.4f}")


def cmd_verify(args):
    from apix_collect.provenance import verify_chain
    from apix_pipeline.quality import run_contract, summarise
    from apix_pipeline import run_index
    conn = _conn()
    chain = verify_chain(conn)
    print("provenance hash chain")
    print(f"  records      {chain['n_records']}")
    print(f"  intact       {chain['intact']}")
    print(f"  tip          {chain['tip_hash'][:32]}...")
    if not chain["intact"]:
        print(f"  FIRST BREAK  seq {chain['first_broken_seq']}")

    quotes = run_index.attach_variant_prices(db.read_quotes(conn, publishable_only=False))
    expected = [r[0] for r in conn.execute("SELECT route FROM dim_route")]
    checks = run_contract(quotes, conn=conn, expected_routes=expected)
    print("\ndata quality contract")
    for c in checks:
        mark = "PASS" if c["passed"] else ("FAIL" if c["severity"] == "BLOCK" else "warn")
        print(f"  [{mark}] {c['severity']:<10s} {c['check_class']:<15s} {c['check_name']}"
              + (f"   observed={c['observed']}" if not c["passed"] else ""))
    s = summarise(checks)
    print(f"\n  {s['n_passed']}/{s['n_checks']} passed")
    if s["blocking"]:
        print(f"  BLOCKING FAILURES: {s['blocking']}")
        return 1
    return 0


def cmd_reproduce(args):
    """Recompute every published number from raw quotes and diff.

    A zero-difference report is the governance demo. It works because the
    engine is pure and the bootstrap is seeded.
    """
    import pandas as pd
    from apix_pipeline import run_index
    cfg = db.load_config()
    conn = _conn()
    published = pd.read_sql_query(
        "SELECT index_code, period, frequency, basis, omega_preset, value, "
        "method_version, weights_version FROM fact_index_value", conn)
    if published.empty:
        print("nothing published yet; run `python cli.py index` first")
        return 1

    weights = db.build_weights(conn, cfg)
    run_index.run(conn, cfg, weights, run_id="reproduce", write_detail=True,
                  enforce_quality=False)
    recomputed = pd.read_sql_query(
        "SELECT index_code, period, frequency, basis, omega_preset, value AS value_new "
        "FROM fact_index_value", conn)

    key = ["index_code", "period", "frequency", "basis", "omega_preset"]
    merged = published.merge(recomputed, on=key, how="outer", indicator=True)
    missing = int((merged["_merge"] != "both").sum())
    both = merged[merged["_merge"] == "both"].copy()
    both["diff"] = (both["value"] - both["value_new"]).abs()
    worst = float(both["diff"].max()) if len(both) else 0.0
    n_diff = int((both["diff"] > 1e-9).sum())

    print("reproducibility report")
    print(f"  published numbers      {len(published)}")
    print(f"  recomputed numbers     {len(recomputed)}")
    print(f"  unmatched keys         {missing}")
    print(f"  numbers differing      {n_diff}")
    print(f"  max abs difference     {worst:.12g}")
    ok = (missing == 0 and n_diff == 0)
    print(f"\n  {'ZERO DIFFERENCES' if ok else 'DIFFERENCES FOUND'}")
    return 0 if ok else 1


def cmd_status(args):
    conn = _conn()
    print(f"database: {db.db_path()}")
    for t in ("dim_route", "dim_carrier", "dim_source", "fact_fare_quote",
              "fact_index_value", "ledger_provenance", "quality_check_result"):
        try:
            print(f"  {t:24s} {db.table_count(conn, t):>8d}")
        except Exception as e:
            print(f"  {t:24s}    n/a ({e})")
    row = conn.execute("SELECT MIN(collected_date) a, MAX(collected_date) b "
                       "FROM fact_fare_quote").fetchone()
    if row and row["a"]:
        print(f"  quote history            {row['a']} .. {row['b']}")
    row = conn.execute("SELECT COUNT(DISTINCT route) n FROM fact_fare_quote").fetchone()
    total = db.table_count(conn, "dim_route")
    if row:
        print(f"  routes with quotes       {row['n']} of {total} in basket "
              f"({100.0 * row['n'] / max(total,1):.1f}% by count)")


def cmd_load_cpi(args):
    """Load the MoSPI CPI workbooks: the back-test comparator and nowcast target."""
    from apix_reference import cpi
    conn = _conn()
    db.init_schema(conn)
    summary = cpi.load_directory(conn, Path(args.dir))
    print(f"rows loaded: {summary['rows_loaded']}")
    for name, info in summary["files"].items():
        print(f"  {name}")
        print(f"     rows={info['rows']:>7d}  base={info['base_year']}  "
              f"levels={info['levels']}")
        print(f"     {info['period_range'][0]} .. {info['period_range'][1]}  "
              f"({info['labels']} labels)")
    for sk in summary["skipped"]:
        print(f"  SKIPPED {sk['file']}: {sk['reason']}")

    air = cpi.find_air_fare_item(conn)
    print("\nair-fare item index present:", "yes" if len(air) else "NO")
    if not len(air):
        print("  The extracts stop at the Transport aggregate. The back-test therefore")
        print("  compares against Transport, not the air fare item -- a weaker comparison")
        print("  that is reported as such. For the item series, pull the item-level")
        print("  extract from https://cpi.mospi.gov.in (COICOP sub-class 07.3.3).")

    print("\navailable comparators (All India):")
    av = cpi.available_series(conn)
    print(av[av.label.str.contains("Transport", case=False)].to_string(index=False))


def _apix_monthly(conn, basis="travel", variant="T", preset=None):
    import pandas as pd
    cfg = db.load_config()
    preset = preset or cfg["method"]["default_omega_preset"]
    return pd.read_sql_query(
        "SELECT period, value FROM fact_index_value WHERE index_code=? AND "
        "frequency='monthly' AND basis=? AND omega_preset=? ORDER BY period",
        conn, params=[f"Nabhsetu-{variant}", basis, preset])


def cmd_backtest(args):
    from apix_pipeline import backtest
    from apix_reference import cpi
    conn = _conn()

    apix = _apix_monthly(conn, basis=args.basis, variant=args.variant)
    if apix.empty:
        print("no monthly Nabhsetu series; run `python cli.py index` first")
        return 1
    syn = bool(conn.execute("SELECT MAX(is_synthetic) s FROM fact_index_value").fetchone()["s"])

    comp = cpi.transport_series(conn, base_year=args.base_year)
    if comp.empty:
        print(f"no CPI comparator for base {args.base_year}; run `python cli.py load-cpi`")
        return 1

    level = "division" if args.base_year == 2024 else "subgroup"
    name = (f"CPI-{args.base_year} {cpi.TRANSPORT_LABEL[args.base_year]} "
            f"(All India, Combined)")
    res = backtest.run(conn, apix, comp, apix_code=f"Nabhsetu-{args.variant}",
                       apix_basis=args.basis, comparator_name=name,
                       comparator_level=level, is_synthetic=syn)

    print(f"back-test: Nabhsetu-{args.variant} ({args.basis} basis)  vs  {name}")
    print(f"  Nabhsetu span       {res['apix_range']}")
    print(f"  comparator span {res['comparator_range']}")
    print(f"  overlapping months: {res['n_overlapping_months']}")
    for c in res["caveats"]:
        print(f"\n  CAVEAT: {c}")
    if not res["reportable"]:
        print("\n  Nothing computed -- see caveat above.")
        return 0
    print("\n  agreement statistics:")
    for k, v in res["statistics"].items():
        ok = isinstance(v, (int, float)) and math.isfinite(v)
        print(f"    {k:<34s} {v:>10.4f}" if ok else f"    {k:<34s}        n/a")
    if res.get("best_lag"):
        b = res["best_lag"]
        print(f"\n  strongest cross-correlation at lag {b['lag_months']:+d} months "
              f"(r={b['corr']:.4f}, n={b['n']})")
        print("   (positive lag = Nabhsetu moves first)")
    return 0


def cmd_nowcast(args):
    from apix_pipeline import nowcast
    from apix_reference import cpi
    conn = _conn()

    apix = _apix_monthly(conn, basis=args.basis)
    if apix.empty:
        print("no monthly Nabhsetu series; run `python cli.py index` first")
        return 1
    syn = bool(conn.execute("SELECT MAX(is_synthetic) s FROM fact_index_value").fetchone()["s"])

    comp = cpi.transport_series(conn, base_year=args.base_year)
    if comp.empty:
        print(f"no CPI series for base {args.base_year}; run `python cli.py load-cpi`")
        return 1

    design = nowcast.build_design(apix, comp)
    fit = nowcast.fit(design, is_synthetic=syn)

    print(f"CPI transport nowcast bridge  (base {args.base_year}, {args.basis} basis)")
    print(f"  target: {fit.spec.get('target')}")
    print(f"  regressors: {fit.spec.get('regressors')}")
    print()
    print(fit.summary())
    if fit.oos:
        print("\n  out-of-sample (expanding window, never a random split):")
        for k, v in fit.oos.items():
            print(f"    {k}: {v}")
    g = nowcast.granger_causality(design)
    print("\n  Granger causality (Nabhsetu -> CPI transport):")
    for k, v in g.items():
        print(f"    {k}: {v}")
    if not fit.interpretable:
        print("\n  ==> COEFFICIENTS ARE NOT REPORTABLE. See the reasons above.")
        print("      The harness is correct and will produce a real answer as soon as")
        print("      enough real (non-synthetic) history exists.")
    return 0


def cmd_serve(args):
    import uvicorn
    uvicorn.run("apix_api.main:app", host=args.host, port=args.port, reload=False)


def main():
    p = argparse.ArgumentParser(prog="apix", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create schema and seed dimensions").set_defaults(fn=cmd_init)

    b = sub.add_parser("backfill", help="build a quote history")
    b.add_argument("--days", type=int, default=90)
    b.add_argument("--end", type=str, default=None, help="YYYY-MM-DD, default today")
    b.add_argument("--all-routes", action="store_true", help="full basket, not the demo subset")
    b.set_defaults(fn=cmd_backfill)

    i = sub.add_parser("index", help="compute and publish the index family")
    i.add_argument("--variants", type=str, default=None, help="e.g. B,T,A")
    i.add_argument("--presets", type=str, default=None, help="e.g. uniform,leisure_tilted")
    i.add_argument("--bootstrap", type=int, default=None, help="bootstrap draws override")
    i.add_argument("--ignore-quality", action="store_true",
                   help="publish despite BLOCK failures (for debugging only)")
    i.set_defaults(fn=cmd_index)

    e = sub.add_parser("elasticity", help="fit eta(tau) and report tau*")
    e.add_argument("--route", type=str, default=None)
    e.set_defaults(fn=cmd_elasticity)

    sub.add_parser("verify", help="hash chain + quality contract").set_defaults(fn=cmd_verify)
    sub.add_parser("reproduce", help="recompute and diff").set_defaults(fn=cmd_reproduce)
    sub.add_parser("status", help="what is in the store").set_defaults(fn=cmd_status)

    lc = sub.add_parser("load-cpi", help="load MoSPI CPI workbooks (comparator + nowcast target)")
    lc.add_argument("--dir", type=str, default="../Datasets")
    lc.set_defaults(fn=cmd_load_cpi)

    bt = sub.add_parser("backtest", help="agreement statistics vs the CPI comparator")
    bt.add_argument("--basis", type=str, default="travel", choices=["book", "travel"])
    bt.add_argument("--variant", type=str, default="T", choices=["B", "T", "A"])
    bt.add_argument("--base-year", type=int, default=2024, choices=[2010, 2012, 2024])
    bt.set_defaults(fn=cmd_backtest)

    nc = sub.add_parser("nowcast", help="fit the CPI transport bridge model")
    nc.add_argument("--basis", type=str, default="travel", choices=["book", "travel"])
    nc.add_argument("--base-year", type=int, default=2024, choices=[2010, 2012, 2024])
    nc.set_defaults(fn=cmd_nowcast)

    s = sub.add_parser("serve", help="run the API and dashboard")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    args = p.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
