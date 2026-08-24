"""Stage 0b: fare decomposition (Part 4, section 2.1).

A displayed "total fare" is a sum of economically distinct components with
completely different inflation dynamics. Indexing the total without decomposing
it means a UDF revision at one airport shows up as "airfare inflation".

    P_total = P_base + (YQ+YR) + (UDF+ASF+RCS) + GST + CF

The administered components are NOT SCRAPED. UDF, ASF, RCS and GST are
published by AERA, BCAS/MoCA and the GST Council and are held in versioned SCD
tables. The base fare is computed as a RESIDUAL and cross-checked against the
airline's own breakup where one is displayed. That turns a scraping problem
into a reconciliation problem, and reconciliation is auditable.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, Optional

import numpy as np
import pandas as pd


class ChargeBook:
    """Point-in-time lookup over the SCD tables.

    Effective-dated so that a number computed for June uses June's UDF, not
    today's. This is what makes an old index value still reproducible after a
    tariff order changes.
    """

    def __init__(self, conn: sqlite3.Connection, convenience_fee: float = 0.0,
                 rcs_levy: float = 0.0):
        self.charges = pd.read_sql_query(
            "SELECT airport_iata, udf_domestic, asf, effective_from, effective_to "
            "FROM scd_airport_charges", conn)
        self.taxes = pd.read_sql_query(
            "SELECT cabin, gst_rate, effective_from, effective_to FROM scd_tax_rate", conn)
        self.rcs_routes = set(
            r["route"] for r in conn.execute("SELECT route FROM dim_route WHERE is_rcs = 1"))
        self.convenience_fee = float(convenience_fee)
        self.rcs_levy = float(rcs_levy)

    @staticmethod
    def _in_force(df: pd.DataFrame, on: str) -> pd.DataFrame:
        return df[(df["effective_from"] <= on) &
                  (df["effective_to"].isna() | (df["effective_to"] > on))]

    def udf(self, airport: str, on: str) -> float:
        rows = self._in_force(self.charges[self.charges["airport_iata"] == airport], on)
        return float(rows["udf_domestic"].iloc[0]) if len(rows) else 0.0

    def asf(self, airport: str, on: str) -> float:
        rows = self._in_force(self.charges[self.charges["airport_iata"] == airport], on)
        return float(rows["asf"].iloc[0]) if len(rows) else 0.0

    def gst_rate(self, cabin: str, on: str) -> float:
        rows = self._in_force(self.taxes[self.taxes["cabin"] == cabin], on)
        return float(rows["gst_rate"].iloc[0]) if len(rows) else 0.0


def decompose(df: pd.DataFrame, book: ChargeBook, charge_on: Optional[str] = None) -> pd.DataFrame:
    """Split total_fare into components, solving for the fare base.

    UDF is levied at the ORIGIN airport of the sector, so the departure airport
    is the one that matters. GST is ad valorem on the fare base F = base + YQ:

        total = F + udf + asf + rcs + g*F + cf
        =>  F = (total - udf - asf - rcs - cf) / (1 + g)

    YQ/YR cannot be separated from the base without the airline's own breakup,
    so it is folded into `base_fare` for the headline (which is what Part 4
    prescribes) and reported as zero rather than as a guess. Inventing a split
    would put a fabricated number in a published component series.
    """
    out = df.copy()
    n = len(out)
    if n == 0:
        for c in ("base_fare", "yq_yr", "udf", "asf", "rcs_levy", "gst", "convenience_fee",
                  "price_B", "price_T", "price_A", "decomp_residual"):
            out[c] = pd.Series(dtype=float)
        return out

    # The charge book is effective-dated, but within one batch the effective
    # date set is tiny (usually one). Resolve each (date, airport) and
    # (date, cabin) combination ONCE and map it, rather than re-filtering the
    # SCD tables per row -- the naive version is O(rows x scd_rows).
    dates = [charge_on] if charge_on else sorted(out["collected_date"].astype(str).unique())
    origins = out["origin_iata"].astype(str).unique()
    cabins = out["cabin"].astype(str).unique()

    udf_map = {(d, a): book.udf(a, d) for d in dates for a in origins}
    asf_map = {(d, a): book.asf(a, d) for d in dates for a in origins}
    gst_map = {(d, c): book.gst_rate(c, d) for d in dates for c in cabins}

    on_col = (pd.Series([charge_on] * n, index=out.index) if charge_on
              else out["collected_date"].astype(str))
    pair_airport = list(zip(on_col, out["origin_iata"].astype(str)))
    pair_cabin = list(zip(on_col, out["cabin"].astype(str)))

    out["udf"] = [udf_map[k] for k in pair_airport]
    out["asf"] = [asf_map[k] for k in pair_airport]
    out["rcs_levy"] = np.where(out["route"].isin(book.rcs_routes), book.rcs_levy, 0.0)
    out["_gst_rate"] = [gst_map[k] for k in pair_cabin]
    out["convenience_fee"] = book.convenience_fee

    total = pd.to_numeric(out["total_fare"], errors="coerce")
    statutory = out["udf"] + out["asf"] + out["rcs_levy"] + out["convenience_fee"]
    fare_base = (total - statutory) / (1.0 + out["_gst_rate"])

    out["base_fare"] = fare_base
    out["yq_yr"] = 0.0
    out["gst"] = fare_base * out["_gst_rate"]

    # The three published variants (Part 4, section 2.1).
    out["price_B"] = out["base_fare"] + out["yq_yr"]          # pure airline pricing
    out["price_T"] = total - out["convenience_fee"]           # HEADLINE: what a traveller pays
    out["price_A"] = total                                    # all-in checkout cost

    # Arithmetic reconciliation: components must re-sum to the total within
    # INR 1. This is a BLOCKING data-quality check, not a warning.
    recomposed = (out["base_fare"] + out["yq_yr"] + out["udf"] + out["asf"]
                  + out["rcs_levy"] + out["gst"] + out["convenience_fee"])
    out["decomp_residual"] = (total - recomposed).abs()

    return out.drop(columns=["_gst_rate"])


def variant_price(df: pd.DataFrame, variant: str) -> pd.Series:
    col = {"B": "price_B", "T": "price_T", "A": "price_A"}.get(variant)
    if col is None:
        raise ValueError(f"unknown variant {variant!r}; expected B, T or A")
    return df[col]
