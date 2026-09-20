from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_container, get_settings, require_api_key
from app.api.schemas.common import SIMULATED_NOTICE, SimulatedEnvelope, SourceStatusResponse
from app.config import DataMode, Settings
from app.services.container import AppContainer

router = APIRouter(prefix="/sources", tags=["sources"])


def _meta(settings: Settings) -> SimulatedEnvelope:
    simulated = settings.data_mode == DataMode.MOCK
    return SimulatedEnvelope(
        is_simulated=simulated,
        data_mode=settings.data_mode,
        notice=SIMULATED_NOTICE if simulated else None,
    )


@router.get("", dependencies=[Depends(require_api_key)])
async def list_sources(
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> dict:
    profiles = await container.registry.list_all()
    return {
        "items": [
            {
                "id": str(item.id),
                "name": item.name,
                "enabled": item.enabled,
                "source_type": item.source_type.value,
                "preferred_adapter": item.capabilities.preferred_adapter.value
                if item.capabilities.preferred_adapter
                else None,
                "temporarily_blocked": item.temporarily_blocked,
                "automation_allowed": item.automation_allowed,
                "terms_review_status": item.terms_review_status.value,
                "robots_status": item.robots_status.value,
                "restriction_reason": item.restriction_reason,
            }
            for item in profiles
        ],
        "meta": _meta(settings).model_dump(),
    }


@router.get("/{source_id}/status", response_model=SourceStatusResponse, dependencies=[Depends(require_api_key)])
async def source_status(
    source_id: str,
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> SourceStatusResponse:
    from uuid import UUID

    try:
        profile = await container.registry.get(UUID(source_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="source not found") from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="source not found")
    circuits = {
        stat.adapter.value: {
            "state": stat.circuit_state.value,
            "consecutive_failures": stat.consecutive_failures,
            "cooldown_until": stat.cooldown_until.isoformat() if stat.cooldown_until else None,
        }
        for stat in profile.adapter_stats
    }
    return SourceStatusResponse(
        id=profile.id,
        name=profile.name,
        enabled=profile.enabled,
        source_type=profile.source_type.value,
        preferred_adapter=profile.capabilities.preferred_adapter.value
        if profile.capabilities.preferred_adapter
        else None,
        last_successful_adapter=profile.capabilities.last_successful_adapter.value
        if profile.capabilities.last_successful_adapter
        else None,
        temporarily_blocked=profile.temporarily_blocked,
        restriction_reason=profile.restriction_reason,
        robots_status=profile.robots_status.value,
        terms_review_status=profile.terms_review_status.value,
        circuit=circuits,
        network_policy=profile.network_policy.model_dump(mode="json"),
        meta=_meta(settings),
    )
