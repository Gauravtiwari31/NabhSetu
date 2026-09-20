from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_settings, require_api_key
from app.api.schemas.common import SIMULATED_NOTICE, SimulatedEnvelope
from app.api.schemas.index import StatusResponse
from app.config import DataMode, Settings
from app.domain.enums import JobStatus
from app.services.container import AppContainer

router = APIRouter(prefix="/v1", tags=["status"], dependencies=[Depends(require_api_key)])


@router.get("/status", response_model=StatusResponse)
async def platform_status(
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> StatusResponse:
    sources = await container.registry.list_all()
    jobs = await container.jobs.list_recent(limit=50)
    run = await container.publications.latest_run()
    simulated = settings.data_mode == DataMode.MOCK
    blocked = sum(1 for item in sources if item.temporarily_blocked)
    enabled = sum(1 for item in sources if item.enabled)
    pending = sum(1 for job in jobs if job.status == JobStatus.PENDING)
    denied = any(job.status == JobStatus.DENIED for job in jobs[:10])
    banner = "mock"
    if not simulated and denied:
        banner = "policy_denied"
    elif not simulated:
        banner = "live"
    return StatusResponse(
        data_mode=settings.data_mode,
        egress_mode=settings.egress_mode.value,
        is_simulated=simulated,
        notice=SIMULATED_NOTICE if simulated else None,
        latest_run_id=None if run is None else run.id,
        latest_run_status=None if run is None else run.status.value,
        blocked_sources=blocked,
        enabled_sources=enabled,
        pending_jobs=pending,
        banner=banner,  # type: ignore[arg-type]
        meta=SimulatedEnvelope(
            is_simulated=simulated,
            data_mode=settings.data_mode,
            notice=SIMULATED_NOTICE if simulated else None,
        ),
    )
