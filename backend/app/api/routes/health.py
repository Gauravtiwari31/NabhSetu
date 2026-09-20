from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from app import __version__
from app.api.deps import get_container
from app.api.schemas.common import SIMULATED_NOTICE, HealthResponse
from app.config import DataMode
from app.services.container import AppContainer

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, container: AppContainer = Depends(get_container)) -> HealthResponse:
    settings = request.app.state.settings
    db_status = "ok"
    overall: str = "ok"
    try:
        await container.sources.session.execute(text("SELECT 1"))
    except Exception:
        db_status = "unavailable"
        overall = "degraded"
    simulated = settings.data_mode == DataMode.MOCK
    return HealthResponse(
        status=overall,  # type: ignore[arg-type]
        service=settings.app_name,
        version=__version__,
        data_mode=settings.data_mode,
        egress_mode=settings.egress_mode.value,
        database=db_status,
        is_simulated=simulated,
        notice=SIMULATED_NOTICE if simulated else None,
    )
