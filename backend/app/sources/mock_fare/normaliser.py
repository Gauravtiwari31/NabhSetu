from __future__ import annotations

from decimal import Decimal

from app.domain.models import CanonicalFareObservation


def normalise_observation(observation: CanonicalFareObservation) -> CanonicalFareObservation:
    observation.origin_airport = observation.origin_airport.upper()
    observation.destination_airport = observation.destination_airport.upper()
    observation.carrier = observation.carrier.upper()
    if observation.operating_carrier:
        observation.operating_carrier = observation.operating_carrier.upper()
    observation.cabin_class = observation.cabin_class.upper()
    observation.currency = observation.currency.upper()
    if observation.duplicate_key is None:
        observation.duplicate_key = observation.compute_duplicate_key()
    if observation.extraction_confidence < Decimal("0"):
        observation.extraction_confidence = Decimal("0")
    return observation
