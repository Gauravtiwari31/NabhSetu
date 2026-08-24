#!/usr/bin/env python
"""Collect every review and test result into one JSON evidence file.

Run before `tools/build_report.py`. Everything the report prints comes from
here, so the PDF cannot contain a number that was not actually measured.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "reports" / "evidence.json"


def sh(cmd, timeout=1800):
    t0 = time.time()
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       cwd=str(ROOT), timeout=timeout)
    return {"cmd": cmd, "rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr,
            "seconds": round(time.time() - t0, 2)}


def main():
    ev = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
    }

    # ---- test suite -------------------------------------------------
    ev["pytest"] = sh(f'"{sys.executable}" -m pytest -o addopts="" -q --durations=15 --tb=short')
    ev["pytest_collect"] = sh(f'"{sys.executable}" -m pytest -o addopts="" --collect-only -q')

    # ---- coverage ---------------------------------------------------
    cov_json = ROOT / "reports" / "coverage.json"
    sh(f'"{sys.executable}" -m coverage run --source=src -m pytest -o addopts="" -q')
    ev["coverage_report"] = sh(f'"{sys.executable}" -m coverage report --precision=1')
    sh(f'"{sys.executable}" -m coverage json -o "{cov_json}" -q')
    if cov_json.exists():
        raw = json.loads(cov_json.read_text(encoding="utf-8"))
        ev["coverage"] = {
            "total_pct": raw["totals"]["percent_covered"],
            "statements": raw["totals"]["num_statements"],
            "missing": raw["totals"]["missing_lines"],
            "files": {k.replace("\\", "/"): {
                "pct": v["summary"]["percent_covered"],
                "statements": v["summary"]["num_statements"],
                "missing": v["summary"]["missing_lines"]}
                for k, v in raw["files"].items()},
        }

    # ---- static analysis --------------------------------------------
    ev["ruff_stats"] = sh(f'"{sys.executable}" -m ruff check src tests cli.py --statistics')
    ev["ruff_serious"] = sh(f'"{sys.executable}" -m ruff check src tests cli.py '
                            f'--select PLR0124,F841,ISC004,F821,E9,B006 --output-format concise')

    # ---- pipeline verification --------------------------------------
    ev["verify"] = sh(f'"{sys.executable}" cli.py verify')
    ev["status"] = sh(f'"{sys.executable}" cli.py status')
    ev["backtest"] = sh(f'"{sys.executable}" cli.py backtest')
    ev["nowcast"] = sh(f'"{sys.executable}" cli.py nowcast')
    ev["elasticity"] = sh(f'"{sys.executable}" cli.py elasticity --route DEL-BOM')

    # ---- numerical validation ---------------------------------------
    ev["engine_validation"] = sh(f'"{sys.executable}" tools/validate_engine.py')

    # ---- API sweep ---------------------------------------------------
    ev["api_sweep"] = sh(f'"{sys.executable}" tools/api_sweep.py')

    # ---- store facts -------------------------------------------------
    try:
        from apix_store import db
        conn = db.connect()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        ev["store"] = {t: db.table_count(conn, t) for t in sorted(tables)}
        row = conn.execute("SELECT MIN(collected_date) a, MAX(collected_date) b "
                           "FROM fact_fare_quote").fetchone()
        ev["store_span"] = [row["a"], row["b"]]
        ev["db_size_mb"] = round(db.db_path().stat().st_size / 1e6, 1)
        conn.close()
    except Exception as e:
        ev["store_error"] = f"{type(e).__name__}: {e}"

    # ---- source size --------------------------------------------------
    loc = {}
    for p in sorted((ROOT / "src").rglob("*.py")):
        loc[str(p.relative_to(ROOT)).replace("\\", "/")] = len(
            p.read_text(encoding="utf-8").splitlines())
    for p in sorted((ROOT / "tests").rglob("*.py")):
        loc[str(p.relative_to(ROOT)).replace("\\", "/")] = len(
            p.read_text(encoding="utf-8").splitlines())
    loc["cli.py"] = len((ROOT / "cli.py").read_text(encoding="utf-8").splitlines())
    ev["loc"] = loc

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ev, indent=2), encoding="utf-8")
    print(f"evidence written: {OUT}")
    print(f"  pytest rc={ev['pytest']['rc']}  ({ev['pytest']['seconds']}s)")
    if "coverage" in ev:
        print(f"  coverage {ev['coverage']['total_pct']:.1f}%")


if __name__ == "__main__":
    main()
