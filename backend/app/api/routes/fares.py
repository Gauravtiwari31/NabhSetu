from fastapi import APIRouter, Depends, Query

from app.api.deps import get_container, get_settings, require_api_key
from app.api.schemas.common import (
    SIMULATED_NOTICE,
    FareListResponse,
    FareObservationResponse,
    SimulatedEnvelope,
)
from app.config import DataMode, Settings
from app.services.container import AppContainer

router = APIRouter(prefix="/fares", tags=["fares"])


@router.get("/latest", response_model=FareListResponse, dependencies=[Depends(require_api_key)])
async def latest_fares(
    origin: str | None = Query(default=None),
    destination: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> FareListResponse:
    rows = await container.observations.list_latest_fares(
        origin=origin, destination=destination, limit=limit
    )
    simulated = settings.data_mode == DataMode.MOCK
    return FareListResponse(
        items=[
            FareObservationResponse(
                observation_id=row.id,
                origin=row.origin_airport,
                destination=row.destination_airport,
                travel_date=row.travel_date,
                lead_time_days=row.lead_time_days,
                carrier=row.carrier,
                flight_number=row.flight_number,
                total_fare=format(row.total_fare, "f"),
                currency=row.currency,
                availability=row.availability.value,
                disposition=row.disposition.value,
                quality_score=format(row.quality_score, "f"),
                is_simulated=row.is_simulated,
                collector=row.collector.value,
                collected_at=row.collected_at.isoformat(),
            )
            for row in rows
        ],
        meta=SimulatedEnvelope(
            is_simulated=simulated or any(row.is_simulated for row in rows),
            data_mode=settings.data_mode,
            notice=SIMULATED_NOTICE if simulated else None,
        ),
    )
