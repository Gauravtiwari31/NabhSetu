from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_container, get_settings, require_api_key
from app.api.schemas.common import (
    SIMULATED_NOTICE,
    CollectionJobCreate,
    CollectionJobResponse,
    SimulatedEnvelope,
)
from app.config import DataMode, Settings
from app.domain.enums import ALLOWED_LEAD_TIMES
from app.domain.models import CollectionError, FareQuery, ProvenanceLink
from app.services.container import AppContainer

router = APIRouter(prefix="/collection-jobs", tags=["collection"])


def _meta(settings: Settings) -> SimulatedEnvelope:
    simulated = settings.data_mode == DataMode.MOCK
    return SimulatedEnvelope(
        is_simulated=simulated,
        data_mode=settings.data_mode,
        notice=SIMULATED_NOTICE if simulated else None,
    )


def build_query(payload: CollectionJobCreate) -> FareQuery:
    observation = payload.observation_date or date.today()
    if payload.travel_date is not None and payload.lead_time_days is not None:
        travel = payload.travel_date
        lead = payload.lead_time_days
    elif payload.travel_date is not None:
        travel = payload.travel_date
        lead = (travel - observation).days
    elif payload.lead_time_days is not None:
        lead = payload.lead_time_days
        travel = observation + timedelta(days=lead)
    else:
        lead = ALLOWED_LEAD_TIMES[0]
        travel = observation + timedelta(days=lead)
    return FareQuery(
        origin=payload.origin,
        destination=payload.destination,
        travel_date=travel,
        observation_date=observation,
        lead_time_days=lead,
        passengers=payload.passengers,
        cabin_class=payload.cabin_class,
        currency=payload.currency,
        source_id=payload.source_id,
    )


@router.post("", response_model=CollectionJobResponse, dependencies=[Depends(require_api_key)])
async def create_job(
    payload: CollectionJobCreate,
    request: Request,
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> CollectionJobResponse:
    try:
        query = build_query(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    request_id = request.headers.get("x-request-id") or "unspecified"
    job_id, result = await container.collection.submit(query, request_id=request_id)
    observations = await container.observations.list_for_job(job_id)
    provenance_rows = await container.observations.provenance_for(
        [job_id] + [item.id for item in observations]
    )
    job = await container.jobs.get(job_id)
    assert job is not None
    return CollectionJobResponse(
        id=job.id,
        status=job.status,
        query=query,
        result_status=job.result_status,
        collector=job.collector,
        is_simulated=job.is_simulated or result.is_simulated,
        observation_ids=[item.id for item in observations],
        errors=result.errors,
        provenance=[
            ProvenanceLink(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                parent_type=row.parent_type,
                parent_id=row.parent_id,
                relation=row.relation,
                content_hash=row.content_hash,
            )
            for row in provenance_rows
        ],
        meta=_meta(settings),
    )


@router.get("", dependencies=[Depends(require_api_key)])
async def list_jobs(
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> dict:
    jobs = await container.jobs.list_recent(limit=50)
    return {
        "items": [
            {
                "id": str(job.id),
                "status": job.status.value,
                "result_status": None if job.result_status is None else job.result_status.value,
                "collector": None if job.collector is None else job.collector.value,
                "is_simulated": job.is_simulated,
                "query": job.query_json,
                "error_summary": job.error_summary,
                "created_at": job.created_at.isoformat(),
            }
            for job in jobs
        ],
        "meta": _meta(settings).model_dump(),
    }


@router.get("/{job_id}", response_model=CollectionJobResponse, dependencies=[Depends(require_api_key)])
async def get_job(
    job_id: UUID,
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> CollectionJobResponse:
    job = await container.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    query = FareQuery.model_validate(job.query_json)
    observations = await container.observations.list_for_job(job_id)
    provenance_rows = await container.observations.provenance_for(
        [job_id] + [item.id for item in observations]
    )
    return CollectionJobResponse(
        id=job.id,
        status=job.status,
        query=query,
        result_status=job.result_status,
        collector=job.collector,
        is_simulated=job.is_simulated,
        observation_ids=[item.id for item in observations],
        errors=(
            [CollectionError(code="JOB", message=job.error_summary)]
            if job.error_summary
            else []
        ),
        provenance=[
            ProvenanceLink(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                parent_type=row.parent_type,
                parent_id=row.parent_id,
                relation=row.relation,
                content_hash=row.content_hash,
            )
            for row in provenance_rows
        ],
        meta=_meta(settings),
    )
