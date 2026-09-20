from __future__ import annotations

KNOWN_CARRIERS = {
    "6E": "IndiGo",
    "9I": "Alliance Air",
    "AI": "Air India",
    "G8": "Go First",
    "I5": "Air India Express / AIX Connect",
    "IX": "Air India Express",
    "OG": "Star Air",
    "QP": "Akasa Air",
    "SG": "SpiceJet",
    "UK": "Vistara",
}


def canonical_carrier(code: str) -> str:
    return code.upper()


def is_known_carrier(code: str) -> bool:
    return canonical_carrier(code) in KNOWN_CARRIERS
