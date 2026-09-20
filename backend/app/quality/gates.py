from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.enums import AvailabilityState, PublicationDisposition, ValidationDisposition
from app.domain.models import CanonicalFareObservation, ValidationFlag


def freshness_flag(observation: CanonicalFareObservation, now: datetime, max_age_hours: int) -> ValidationFlag | None:
    age = now - observation.collected_at
    if age <= timedelta(hours=max_age_hours):
        return None
    return ValidationFlag(
        code="STALE_QUOTE",
        message="observation is older than the publication freshness gate",
        disposition=ValidationDisposition.FLAGGED,
        details={"max_age_hours": max_age_hours},
    )


def sold_out_flag(observation: CanonicalFareObservation) -> ValidationFlag | None:
    if observation.seat_or_fare_availability != AvailabilityState.SOLD_OUT:
        return None
    return ValidationFlag(
        code="SOLD_OUT",
        message="sold-out cells are quarantined from publication",
        disposition=ValidationDisposition.FLAGGED,
    )


def minimum_sample_flag(n_matched: int, n_min: int) -> ValidationFlag | None:
    if n_matched >= n_min:
        return None
    return ValidationFlag(
        code="MIN_SAMPLE",
        message="cell is below the publication sample gate",
        disposition=ValidationDisposition.FLAGGED,
        details={"n_matched": n_matched, "n_min": n_min},
    )
