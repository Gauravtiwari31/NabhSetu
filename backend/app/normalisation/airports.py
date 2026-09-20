from __future__ import annotations

KNOWN_AIRPORTS = {
    "AMD": "Sardar Vallabhbhai Patel International",
    "BLR": "Kempegowda International",
    "BOM": "Chhatrapati Shivaji Maharaj International",
    "CCU": "Netaji Subhas Chandra Bose International",
    "COK": "Cochin International",
    "DEL": "Indira Gandhi International",
    "GAU": "Lokpriya Gopinath Bordoloi International",
    "GOI": "Manohar International / Goa",
    "HYD": "Rajiv Gandhi International",
    "IDR": "Devi Ahilya Bai Holkar",
    "JAI": "Jaipur International",
    "LKO": "Chaudhary Charan Singh International",
    "MAA": "Chennai International",
    "NAG": "Dr. Babasaheb Ambedkar International",
    "PAT": "Jay Prakash Narayan International",
    "PNQ": "Pune",
}


def canonical_airport(code: str) -> str:
    return code.upper()


def is_known_airport(code: str) -> bool:
    return canonical_airport(code) in KNOWN_AIRPORTS
