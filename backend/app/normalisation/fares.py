from __future__ import annotations

from decimal import Decimal

from app.domain.enums import ValidationDisposition
from app.domain.models import CanonicalFareObservation, ValidationFlag


def component_flags(observation: CanonicalFareObservation) -> list[ValidationFlag]:
    flags: list[ValidationFlag] = []
    parts = [
        observation.base_fare,
        observation.taxes,
        observation.airport_fee,
        observation.udf,
        observation.convenience_fee,
        observation.other_fee,
    ]
    known = [part for part in parts if part is not None]
    if observation.base_fare is not None and observation.total_fare < observation.base_fare:
        flags.append(
            ValidationFlag(
                code="TOTAL_LT_BASE",
                message="total fare is less than base fare",
                disposition=ValidationDisposition.FLAGGED,
            )
        )
    if len(known) == 6:
        summed = sum(known, Decimal("0.00"))
        if abs(summed - observation.total_fare) > Decimal("0.05"):
            flags.append(
                ValidationFlag(
                    code="COMPONENT_MISMATCH",
                    message="fare components do not sum to total",
                    disposition=ValidationDisposition.FLAGGED,
                    details={"sum": format(summed, "f"), "total": format(observation.total_fare, "f")},
                )
            )
    elif observation.base_fare is None or observation.taxes is None:
        flags.append(
            ValidationFlag(
                code="COMPONENTS_INCOMPLETE",
                message="one or more fare components were not published by the source",
                disposition=ValidationDisposition.FLAGGED,
            )
        )
    return flags
