from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from apix_index.elasticity import elasticity_by_period
from apix_index.types import ApwIndex
from app.api.deps import get_container, get_settings, require_api_key
from app.api.schemas.common import SIMULATED_NOTICE, SimulatedEnvelope
from app.api.schemas.index import (
    CellListResponse,
    CellResponse,
    CoverageResponse,
    ElasticityResponse,
    IndexPoint,
    IndexSeriesResponse,
    ProvenanceResponse,
    decimal_string,
)
from app.config import DataMode, Settings
from app.domain.enums import IndexFrequency
from app.services.container import AppContainer

router = APIRouter(prefix="/v1", tags=["index"], dependencies=[Depends(require_api_key)])


def _meta(settings: Settings, *, simulated: bool | None = None) -> SimulatedEnvelope:
    flag = settings.data_mode == DataMode.MOCK if simulated is None else simulated
    return SimulatedEnvelope(
        is_simulated=flag,
        data_mode=settings.data_mode,
        notice=SIMULATED_NOTICE if flag else None,
    )


def _point(row) -> IndexPoint:
    return IndexPoint(
        period=row.period,
        value=format(row.value, "f"),
        se=decimal_string(row.se),
        ci_low=decimal_string(row.ci_low),
        ci_high=decimal_string(row.ci_high),
        coverage_pct=decimal_string(row.coverage_pct),
        n_matched=row.n_matched,
        route=row.route,
        apw_days=row.apw_days,
        is_simulated=row.is_simulated,
        method_version=row.method_version,
        basket_version=row.basket_version,
        weights_version=row.weights_version,
        frequency=row.frequency.value,
        series=row.series,
    )


@router.get("/index", response_model=IndexSeriesResponse)
async def index_series(
    frequency: IndexFrequency = Query(default=IndexFrequency.DAILY),
    series: str = Query(default="headline"),
    route: str | None = None,
    apw_days: int | None = None,
    run_id: UUID | None = None,
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> IndexSeriesResponse:
    rows = await container.publications.series(
        series=series, frequency=frequency, route=route, apw_days=apw_days, run_id=run_id
    )
    run = await container.publications.get_run(run_id) if run_id else await container.publications.latest_run()
    simulated = settings.data_mode == DataMode.MOCK or any(row.is_simulated for row in rows)
    return IndexSeriesResponse(
        items=[_point(row) for row in rows],
        run_id=None if run is None else run.id,
        meta=_meta(settings, simulated=simulated),
    )


@router.get("/index/cells", response_model=CellListResponse)
async def index_cells(
    route: str | None = None,
    run_id: UUID | None = None,
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> CellListResponse:
    run = await container.publications.get_run(run_id) if run_id else await container.publications.latest_run()
    if run is None:
        raise HTTPException(status_code=404, detail="no published index run")
    rows = await container.publications.cells(run.id, route=route)
    return CellListResponse(
        items=[
            CellResponse(
                period=row.period,
                route=row.route,
                carrier=row.carrier,
                apw_days=row.apw_days,
                matched=decimal_string(row.matched),
                laf=decimal_string(row.laf),
                availability=format(row.availability, "f"),
                adjusted=decimal_string(row.adjusted),
                n_matched=row.n_matched,
                n_quotes=row.n_quotes,
                suppressed=row.suppressed,
            )
            for row in rows
        ],
        run_id=run.id,
        meta=_meta(settings, simulated=run.is_simulated),
    )


@router.get("/coverage", response_model=CoverageResponse)
async def coverage(
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> CoverageResponse:
    run = await container.publications.latest_run()
    return CoverageResponse(
        run_id=None if run is None else run.id,
        coverage_pct=decimal_string(None if run is None else run.coverage_pct),
        n_quotes=0 if run is None else run.n_quotes,
        n_cells=0 if run is None else run.n_cells,
        diagnostics={} if run is None else run.diagnostics_json,
        meta=_meta(settings, simulated=False if run is None else run.is_simulated),
    )


@router.get("/elasticity", response_model=ElasticityResponse)
async def elasticity(
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> ElasticityResponse:
    rows = await container.publications.series(series="apw", frequency=IndexFrequency.DAILY)
    points = [
        ApwIndex(
            period=row.period.isoformat(),
            apw_days=int(row.apw_days or 0),
            value=row.value,
            n_routes=0,
            n_matched=row.n_matched,
            coverage_pct=row.coverage_pct or 0,
        )
        for row in rows
        if row.apw_days is not None
    ]
    return ElasticityResponse(items=elasticity_by_period(points), meta=_meta(settings))


@router.get("/provenance", response_model=ProvenanceResponse)
async def provenance(
    run_id: UUID | None = None,
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> ProvenanceResponse:
    run = await container.publications.get_run(run_id) if run_id else await container.publications.latest_run()
    basket = await container.publications.latest_basket()
    weights = await container.publications.latest_weights()
    return ProvenanceResponse(
        run_id=None if run is None else run.id,
        input_hash=None if run is None else run.input_hash,
        output_hash=None if run is None else run.output_hash,
        method_version=None if run is None else run.method_version,
        basket_version=None if basket is None else basket.version,
        weights_version=None if weights is None else weights.version,
        is_simulated=settings.data_mode == DataMode.MOCK if run is None else run.is_simulated,
        meta=_meta(settings, simulated=settings.data_mode == DataMode.MOCK if run is None else run.is_simulated),
    )
