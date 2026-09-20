"""Lead-time elasticity of the traveller-paid index."""

from __future__ import annotations

from decimal import Decimal

from apix_index.decimal_math import ln, to_decimal
from apix_index.types import ApwIndex


def log_log_elasticity(index_a, index_b, tau_a, tau_b) -> Decimal | None:
    left = to_decimal(index_a)
    right = to_decimal(index_b)
    lead_a = to_decimal(tau_a)
    lead_b = to_decimal(tau_b)
    if left <= 0 or right <= 0 or lead_a <= 0 or lead_b <= 0 or lead_a == lead_b:
        return None
    return (ln(left) - ln(right)) / (ln(lead_a) - ln(lead_b))


def elasticity_by_period(by_apw: list[ApwIndex]) -> list[dict]:
    grouped: dict[str, dict[int, Decimal]] = {}
    for row in by_apw:
        grouped.setdefault(row.period, {})[int(row.apw_days)] = row.value
    rows: list[dict] = []
    for period, table in sorted(grouped.items()):
        windows = sorted(table)
        pairs = []
        for left, right in zip(windows, windows[1:]):
            elasticity = log_log_elasticity(table[left], table[right], left, right)
            pairs.append(
                {
                    "from_apw": left,
                    "to_apw": right,
                    "elasticity": None if elasticity is None else format(elasticity, "f"),
                }
            )
        near = table.get(1)
        far = table.get(45) or table.get(max(windows))
        headline = log_log_elasticity(near, far, 1, max(windows)) if near and far else None
        rows.append(
            {
                "period": period,
                "near_far_elasticity": None if headline is None else format(headline, "f"),
                "pairs": pairs,
            }
        )
    return rows
