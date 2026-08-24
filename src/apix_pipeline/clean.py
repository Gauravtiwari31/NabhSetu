"""Stage 0: raw quote to cleaned price (Part 4, section 2.2).

Fare quotes contain genuine extremes (last-seat pricing) and genuine errors
(parse failures, currency confusion, promotional glitches). The cleaning rule
must remove the second without deleting the first, BECAUSE THE FIRST IS THE
SIGNAL.

The governing discipline is DISPOSITION, NOT DELETION. A flagged quote is never
silently dropped. It is written to the store with `quality_flag` (what the
detector found) and `disposition` (what the pipeline did about it) as separate
columns -- conflating them would lose the ability to re-run cleaning under
different thresholds. The published index uses ACCEPTED and WINSORISED; the
audit endpoint exposes all four.

All work is in log space.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

MAD_TO_SIGMA = 0.6745   # makes MAD a consistent estimator of sigma under normality

# Upper plausibility bound on a single domestic economy one-way adult fare.
# Deliberately generous: the gate is for parse failures, and wrongly deleting
# a real surge fare biases the index down during exactly the episodes that
# matter most.
FARE_CEILING_INR = 90_000.0

DISPOSITIONS = ("ACCEPTED", "WINSORISED", "EXCLUDED", "QUARANTINED")


def _cell_key(df: pd.DataFrame) -> pd.Series:
    return df["route"] + "|" + df["carrier"] + "|" + df["apw_days"].astype(str)


def hard_validity_gates(df: pd.DataFrame, distances: Optional[Dict[str, float]] = None,
                        apw_windows=(1, 7, 15, 30, 45)) -> pd.DataFrame:
    """Deterministic rejects, not statistical ones. These are EXCLUDED outright.

    A quote failing one of these is not an unusual price; it is not a price.
    """
    out = df.copy()
    total = pd.to_numeric(out["total_fare"], errors="coerce")

    # The gates must work on raw quotes too, before decompose() has attached the
    # component columns -- otherwise a batch that fails decomposition cannot be
    # gated at all. Missing components contribute a statutory floor of zero.
    def component(name: str) -> pd.Series:
        if name not in out.columns:
            return pd.Series(0.0, index=out.index)
        return pd.to_numeric(out[name], errors="coerce").fillna(0.0)

    statutory = component("udf") + component("asf") + component("rcs_levy")

    reasons = pd.Series([""] * len(out), index=out.index, dtype=object)

    def flag(mask, label):
        nonlocal reasons
        mask = mask.fillna(False)
        reasons = reasons.where(~(mask & (reasons == "")), label)

    flag(total.isna() | (total <= 0), "NONPOSITIVE_FARE")
    flag(total < statutory, "BELOW_STATUTORY_FLOOR")
    flag(out["currency"].ne("INR"), "NON_INR_CURRENCY")
    flag(~out["apw_days"].isin(list(apw_windows)), "APW_NOT_IN_WINDOW_SET")
    flag(out["cabin"].isin(["economy", "other_than_economy"]).eq(False), "BAD_CABIN")

    # Fare must be plausible for the great-circle distance. The gate exists to
    # catch PARSE FAILURES -- currency confusion, a dropped decimal, a fare
    # scraped from the wrong DOM node -- not to trim expensive fares. Last-seat
    # pricing is signal and must survive this.
    #
    #   reference fare  ~  INR 900 fixed cost + INR 1.6/km
    #   floor  = 0.35 x reference   (below this it is not a fare)
    #   ceiling: no domestic economy one-way one-adult fare plausibly exceeds
    #            FARE_CEILING_INR; a quote above it is a parse artefact.
    if distances:
        km = out["route"].map(distances).fillna(1000)
        reference = 900 + 1.6 * km
        implausible = (total < 0.35 * reference) | (total > FARE_CEILING_INR)
        flag(implausible, "IMPLAUSIBLE_FOR_DISTANCE")

    out["gate_reason"] = reasons
    out["gate_failed"] = reasons.ne("")
    return out


def flag_outliers(df: pd.DataFrame, tukey_k: float = 3.0, hampel_z: float = 3.5,
                  price_col: str = "price_T") -> pd.DataFrame:
    """Tukey fences and a Hampel/MAD filter, both within cell, both on logs.

    The Tukey multiplier is 3, not the usual 1.5: fares are legitimately
    dispersed and 1.5 would trim real observations. The Hampel filter runs
    alongside because MAD is more robust than quartiles for small cells.
    """
    out = df.copy()
    out["_cell"] = _cell_key(out)
    price = pd.to_numeric(out[price_col], errors="coerce")
    out["_y"] = np.log(price.where(price > 0))

    out["quality_flag"] = out.get("gate_reason", pd.Series([""] * len(out), index=out.index))
    out["fence_low"] = np.nan
    out["fence_high"] = np.nan

    for cell, grp in out.groupby(["_cell", "collected_date"], sort=False):
        y = grp["_y"].dropna()
        if len(y) < 4:
            continue
        q1, q3 = np.percentile(y, [25, 75])
        iqr = q3 - q1
        lo, hi = q1 - tukey_k * iqr, q3 + tukey_k * iqr
        out.loc[grp.index, "fence_low"] = lo
        out.loc[grp.index, "fence_high"] = hi

        tukey_hit = (grp["_y"] < lo) | (grp["_y"] > hi)

        m = float(np.median(y))
        mad = float(np.median(np.abs(y - m)))
        if mad > 0:
            z = MAD_TO_SIGMA * (grp["_y"] - m) / mad
            hampel_hit = z.abs() > hampel_z
        else:
            hampel_hit = pd.Series(False, index=grp.index)

        both = (tukey_hit.fillna(False) | hampel_hit.fillna(False))
        blank = out.loc[grp.index, "quality_flag"].eq("") | out.loc[grp.index, "quality_flag"].isna()
        out.loc[grp.index[both & blank], "quality_flag"] = "OUTLIER_CELL"

    return out


def longitudinal_jump_test(df: pd.DataFrame, jump_sigma: float = 3.0,
                           price_col: str = "price_T") -> pd.DataFrame:
    """Flag a quote whose own log-relative to its previous observation is extreme.

    This catches parse regressions that survive the cross-sectional filters --
    a value that is unremarkable among today's quotes but impossible as a
    movement of THAT product.
    """
    out = df.copy()
    key = ["route", "carrier", "apw_days", "flight_number", "fare_family"]
    price = pd.to_numeric(out[price_col], errors="coerce")
    out["_ly"] = np.log(price.where(price > 0))
    out = out.sort_values(key + ["collected_date"])
    out["_prev"] = out.groupby(key, sort=False)["_ly"].shift(1)
    out["_jump"] = (out["_ly"] - out["_prev"]).abs()

    sigma = out.groupby(_cell_key(out), sort=False)["_jump"].transform(
        lambda s: s.std(ddof=1) if s.notna().sum() > 2 else np.nan)
    hit = out["_jump"] > (jump_sigma * sigma)
    blank = out["quality_flag"].eq("") | out["quality_flag"].isna()
    out.loc[hit.fillna(False) & blank, "quality_flag"] = "LONGITUDINAL_JUMP"
    return out.drop(columns=["_ly", "_prev", "_jump"])


def assign_dispositions(df: pd.DataFrame, price_col: str = "price_T") -> pd.DataFrame:
    """Turn flags into dispositions, winsorising rather than deleting.

    Winsorisation caps at the fence:
        y_w = min( max(y, Q1 - k*IQR), Q3 + k*IQR )
    so an extreme-but-real last-seat fare still contributes its direction to
    the index instead of vanishing from it.
    """
    out = df.copy()
    out["disposition"] = "ACCEPTED"
    out.loc[out.get("gate_failed", False) == True, "disposition"] = "EXCLUDED"  # noqa: E712

    # Sold-out rows carry no price. They are not EXCLUDED as bad data -- they
    # are a price signal, and the availability adjustment consumes them via the
    # fare-family counts. They are QUARANTINED so they stay visible on the
    # audit endpoint without entering the matched sample.
    if "is_sold_out" in out.columns:
        out.loc[out["is_sold_out"].fillna(0).astype(int) == 1, "disposition"] = "QUARANTINED"
        out.loc[out["is_sold_out"].fillna(0).astype(int) == 1, "quality_flag"] = "SOLD_OUT"

    winsor = (out["quality_flag"] == "OUTLIER_CELL") & (out["disposition"] == "ACCEPTED")
    y = out["_y"]
    capped = np.minimum(np.maximum(y, out["fence_low"]), out["fence_high"])
    out.loc[winsor, price_col] = np.exp(capped[winsor])
    out.loc[winsor, "disposition"] = "WINSORISED"

    # Record the capped value on a column that SURVIVES persistence. The cap was
    # previously applied only to the in-memory price column, while the store kept
    # `total_fare` and the index recomputed prices from it -- so a quote labelled
    # WINSORISED silently entered the index at its full uncapped value and the
    # disposition was a claim about something that had not happened.
    if "total_fare_capped" not in out.columns:
        out["total_fare_capped"] = np.nan
    fee = (pd.to_numeric(out["convenience_fee"], errors="coerce").fillna(0.0)
           if "convenience_fee" in out.columns else 0.0)
    if price_col == "price_T":
        out.loc[winsor, "total_fare_capped"] = out.loc[winsor, price_col] + (
            fee[winsor] if hasattr(fee, "__getitem__") and not np.isscalar(fee) else fee)
    else:
        out.loc[winsor, "total_fare_capped"] = out.loc[winsor, price_col]

    jump = (out["quality_flag"] == "LONGITUDINAL_JUMP") & (out["disposition"] == "ACCEPTED")
    out.loc[jump, "disposition"] = "QUARANTINED"

    out["quality_flag"] = out["quality_flag"].replace("", None)
    return out.drop(columns=[c for c in ("_y", "_cell") if c in out.columns])


def clean(df: pd.DataFrame, distances: Optional[Dict[str, float]] = None,
          tukey_k: float = 3.0, hampel_z: float = 3.5, jump_sigma: float = 3.0,
          apw_windows=(1, 7, 15, 30, 45), price_col: str = "price_T") -> pd.DataFrame:
    """Run the full Stage 0 sequence and return quotes with dispositions set."""
    out = hard_validity_gates(df, distances=distances, apw_windows=apw_windows)
    out = flag_outliers(out, tukey_k=tukey_k, hampel_z=hampel_z, price_col=price_col)
    out = longitudinal_jump_test(out, jump_sigma=jump_sigma, price_col=price_col)
    out = assign_dispositions(out, price_col=price_col)
    return out


def disposition_summary(df: pd.DataFrame) -> Dict[str, int]:
    return {k: int(v) for k, v in df["disposition"].value_counts().to_dict().items()}
