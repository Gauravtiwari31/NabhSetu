from __future__ import annotations

from decimal import Decimal

from app.domain.enums import ValidationDisposition
from app.domain.models import CanonicalFareObservation, ValidationFlag


def outlier_flags(observation: CanonicalFareObservation) -> list[ValidationFlag]:
    flags: list[ValidationFlag] = []
    if observation.total_fare == 0:
        flags.append(
            ValidationFlag(
                code="ZERO_FARE",
                message="total fare is zero",
                disposition=ValidationDisposition.FLAGGED,
            )
        )
    if observation.total_fare > Decimal("500000"):
        flags.append(
            ValidationFlag(
                code="UNREALISTIC_FARE",
                message="total fare exceeds the configured plausibility ceiling",
                disposition=ValidationDisposition.FLAGGED,
            )
        )
    return flags
