from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.domain.enums import CollectorModality, ValidationDisposition
from app.domain.models import CanonicalFareObservation, ValidationFlag
from app.normalisation.airports import is_known_airport
from app.normalisation.carriers import is_known_carrier
from app.normalisation.fares import component_flags
from app.quality.outliers import outlier_flags


def validate_observation(observation: CanonicalFareObservation) -> list[ValidationFlag]:
    flags: list[ValidationFlag] = []
    if not is_known_airport(observation.origin_airport) or not is_known_airport(observation.destination_airport):
        flags.append(
            ValidationFlag(
                code="UNKNOWN_AIRPORT",
                message="airport code is not in the seeded universe",
                disposition=ValidationDisposition.FLAGGED,
            )
        )
    if not is_known_carrier(observation.carrier):
        flags.append(
            ValidationFlag(
                code="UNKNOWN_CARRIER",
                message="carrier code is not in the seeded universe",
                disposition=ValidationDisposition.FLAGGED,
            )
        )
    flags.extend(component_flags(observation))
    flags.extend(outlier_flags(observation))
    return flags


def disposition_from(flags: list[ValidationFlag]) -> ValidationDisposition:
    if any(flag.disposition == ValidationDisposition.EXCLUDED for flag in flags):
        return ValidationDisposition.EXCLUDED
    if any(flag.disposition == ValidationDisposition.FLAGGED for flag in flags):
        return ValidationDisposition.FLAGGED
    return ValidationDisposition.VALID


def quality_score(observation: CanonicalFareObservation, settings: Settings, flags: list[ValidationFlag]) -> Decimal:
    mapping = {
        CollectorModality.MOCK: settings.confidence_mock,
        CollectorModality.PUBLIC_API: settings.confidence_public_api,
        CollectorModality.STRUCTURED_FEED: settings.confidence_structured_feed,
        CollectorModality.STATIC_HTML: settings.confidence_static_html,
        CollectorModality.EMBEDDED_JSON: settings.confidence_embedded_json,
        CollectorModality.PLAYWRIGHT_NETWORK: settings.confidence_playwright_network,
        CollectorModality.PLAYWRIGHT_DOM: settings.confidence_playwright_dom,
        CollectorModality.DOCUMENT: settings.confidence_document,
        CollectorModality.VISUAL: settings.confidence_visual,
    }
    score = mapping.get(observation.collector, Decimal("0.80"))
    penalty = Decimal("0.02") * len(flags)
    result = score - penalty
    if result < Decimal("0.10"):
        return Decimal("0.10")
    return result.quantize(Decimal("0.01"))
