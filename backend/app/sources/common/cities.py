from __future__ import annotations

CITY_LABELS: dict[str, tuple[str, ...]] = {
    "AMD": ("Ahmedabad",),
    "BLR": ("Bengaluru", "Bangalore"),
    "BOM": ("Mumbai", "Bombay"),
    "CCU": ("Kolkata", "Calcutta"),
    "COK": ("Kochi", "Cochin"),
    "DEL": ("Delhi", "New Delhi"),
    "GAU": ("Guwahati",),
    "GOI": ("Goa",),
    "HYD": ("Hyderabad",),
    "JAI": ("Jaipur",),
    "LKO": ("Lucknow",),
    "MAA": ("Chennai", "Madras"),
    "PNQ": ("Pune",),
}

CITY_SLUGS: dict[str, str] = {
    "AMD": "ahmedabad",
    "BLR": "bengaluru",
    "BOM": "mumbai",
    "CCU": "kolkata",
    "COK": "kochi",
    "DEL": "new-delhi",
    "GAU": "guwahati",
    "GOI": "goa",
    "HYD": "hyderabad",
    "JAI": "jaipur",
    "LKO": "lucknow",
    "MAA": "chennai",
    "PNQ": "pune",
}


def labels_for(code: str) -> tuple[str, ...]:
    code = code.upper()
    extra = CITY_LABELS.get(code, ())
    return extra + (code,)
