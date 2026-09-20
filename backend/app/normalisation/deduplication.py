from __future__ import annotations

from app.domain.models import CanonicalFareObservation


def apply_duplicate_key(observation: CanonicalFareObservation, bucket_seconds: int = 60) -> CanonicalFareObservation:
    observation.duplicate_key = observation.compute_duplicate_key(bucket_seconds)
    return observation
