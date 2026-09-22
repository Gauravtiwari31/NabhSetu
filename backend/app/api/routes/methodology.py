from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_settings, require_api_key
from app.api.schemas.common import SIMULATED_NOTICE, SimulatedEnvelope
from app.api.schemas.index import BasketResponse, MethodologyResponse, WeightsResponse
from app.config import DataMode, Settings
from app.pipeline.method_config import load_basket, load_method_config, load_weight_set
from app.services.container import AppContainer

router = APIRouter(prefix="/v1", tags=["methodology"], dependencies=[Depends(require_api_key)])


def _meta(settings: Settings) -> SimulatedEnvelope:
    simulated = settings.data_mode == DataMode.MOCK
    return SimulatedEnvelope(
        is_simulated=simulated,
        data_mode=settings.data_mode,
        notice=SIMULATED_NOTICE if simulated else None,
    )


@router.get("/methodology", response_model=MethodologyResponse)
async def methodology(settings: Settings = Depends(get_settings)) -> MethodologyResponse:
    config = load_method_config(settings)
    omega = config.omega_vector()
    return MethodologyResponse(
        method_version=config.method_version,
        variant=config.variant,
        basis=config.basis,
        omega_preset=config.omega_preset,
        omega={str(key): format(value, "f") for key, value in omega.items()},
        apw_windows=list(config.apw_windows),
        n_min=config.n_min,
        notes=[
            "APIx-T is a traveller-paid Jevons elementary index with Young aggregation.",
            "Late entrants are not chain-linked; unmatched cells are suppressed.",
            "Availability adjustment blends matched and lowest-available-fare indices.",
            "Official DGCA/CPI figures are imported from checksummed public files only.",
        ],
        meta=_meta(settings),
    )


@router.get("/basket", response_model=BasketResponse)
async def basket(
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> BasketResponse:
    row = await container.publications.latest_basket()
    payload = load_basket(settings)
    return BasketResponse(
        version=payload.get("version") if row is None else row.version,
        name=payload.get("name", "Nabhsetu basket") if row is None else row.name,
        routes=list(payload.get("routes") or []) if row is None else list(row.routes_json or []),
        lead_windows=list(payload.get("lead_windows") or []) if row is None else list(row.lead_windows_json or []),
        carriers=list(payload.get("carriers") or []) if row is None else list(row.carriers_json or []),
        config_hash="" if row is None else row.config_hash,
        meta=_meta(settings),
    )


@router.get("/weights", response_model=WeightsResponse)
async def weights(
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> WeightsResponse:
    row = await container.publications.latest_weights()
    weight_set, payload = load_weight_set(settings)
    route_weights = (
        {key: format(value, "f") for key, value in weight_set.route_weights.items()}
        if row is None
        else {key: str(value) for key, value in (row.route_weights_json or {}).items()}
    )
    carrier_weights = (
        {
            route: {carrier: format(value, "f") for carrier, value in table.items()}
            for route, table in weight_set.carrier_weights.items()
        }
        if row is None
        else {
            route: {carrier: str(value) for carrier, value in table.items()}
            for route, table in (row.carrier_weights_json or {}).items()
        }
    )
    return WeightsResponse(
        version=payload.get("version", "v1") if row is None else row.version,
        source=payload.get("source", "declared") if row is None else row.source,
        checksum=None if row is None else row.checksum,
        route_weights=route_weights,
        carrier_weights=carrier_weights,
        meta=_meta(settings),
    )
