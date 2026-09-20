from __future__ import annotations

from app.domain.enums import AvailabilityState, PublicationDisposition, ValidationDisposition
from app.domain.models import CanonicalFareObservation, ValidationFlag


OUTLIER_CODES = {"TUKEY_OUTLIER", "HAMPEL_OUTLIER", "UNREALISTIC_FARE"}
EXCLUDE_CODES = {"UNKNOWN_AIRPORT", "UNKNOWN_CARRIER"}


def map_publication_disposition(
    observation: CanonicalFareObservation,
    flags: list[ValidationFlag],
    *,
    winsorised: bool = False,
) -> PublicationDisposition:
    if any(flag.disposition == ValidationDisposition.EXCLUDED for flag in flags):
        return PublicationDisposition.EXCLUDED
    if any(flag.code in EXCLUDE_CODES for flag in flags):
        return PublicationDisposition.EXCLUDED
    if observation.seat_or_fare_availability == AvailabilityState.SOLD_OUT:
        return PublicationDisposition.QUARANTINED
    if any(flag.code == "STALE_QUOTE" for flag in flags):
        return PublicationDisposition.QUARANTINED
    if any(flag.code == "ZERO_FARE" for flag in flags):
        return PublicationDisposition.EXCLUDED
    if winsorised or any(flag.code in OUTLIER_CODES for flag in flags):
        return PublicationDisposition.WINSORISED
    if any(flag.disposition == ValidationDisposition.EXCLUDED for flag in flags):
        return PublicationDisposition.EXCLUDED
    return PublicationDisposition.ACCEPTED
