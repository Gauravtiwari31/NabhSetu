from __future__ import annotations

from datetime import date, timedelta

from app.domain.enums import ALLOWED_LEAD_TIMES
from app.domain.models import FareQuery


class QueryScheduler:
    """Expand an observation date into the official lead-time windows."""

    def expand(
        self,
        *,
        origin: str,
        destination: str,
        observation_date: date,
        passengers: int = 1,
        cabin_class: str = "ECONOMY",
        currency: str = "INR",
        source_id=None,
        lead_times: tuple[int, ...] = ALLOWED_LEAD_TIMES,
    ) -> list[FareQuery]:
        return [
            FareQuery(
                origin=origin,
                destination=destination,
                observation_date=observation_date,
                travel_date=observation_date + timedelta(days=lead),
                lead_time_days=lead,
                passengers=passengers,
                cabin_class=cabin_class,
                currency=currency,
                source_id=source_id,
            )
            for lead in lead_times
        ]
