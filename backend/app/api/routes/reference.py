from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_container, get_settings, require_api_key
from app.api.schemas.common import SIMULATED_NOTICE, SimulatedEnvelope
from app.api.schemas.index import BacktestResponse, decimal_string
from app.backtesting.compare import compare_monthly
from app.config import DataMode, Settings
from app.domain.enums import IndexFrequency
from app.pipeline.run_index import IndexPublisher
from app.reference_data.cpi.loader import load_cpi_file
from app.reference_data.dgca.loader import load_dgca_file
from app.services.container import AppContainer

router = APIRouter(prefix="/v1", tags=["reference"], dependencies=[Depends(require_api_key)])


def _meta(settings: Settings) -> SimulatedEnvelope:
    simulated = settings.data_mode == DataMode.MOCK
    return SimulatedEnvelope(
        is_simulated=simulated,
        data_mode=settings.data_mode,
        notice=SIMULATED_NOTICE if simulated else None,
    )


@router.post("/index/publish")
async def publish_index(
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> dict:
    publisher = IndexPublisher(settings, container.observations, container.publications)
    try:
        result = await publisher.publish()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    latest = result.headline[-1] if result.headline else None
    return {
        "periods": len(result.headline),
        "latest_period": None if latest is None else latest.period,
        "latest_value": None if latest is None else format(latest.value, "f"),
        "diagnostics": result.diagnostics,
        "meta": _meta(settings).model_dump(),
    }


@router.post("/reference/dgca")
async def import_dgca(
    path: str,
    source_url: str | None = None,
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="DGCA file not found")
    rows = load_dgca_file(file_path, source_url=source_url)
    for row in rows:
        await container.publications.add_reference(row)
    return {"imported": len(rows), "file": file_path.name, "meta": _meta(settings).model_dump()}


@router.post("/reference/cpi")
async def import_cpi(
    path: str,
    source_url: str | None = None,
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="CPI file not found")
    rows = load_cpi_file(file_path, source_url=source_url)
    for row in rows:
        await container.publications.add_reference(row)
    return {"imported": len(rows), "file": file_path.name, "meta": _meta(settings).model_dump()}


@router.get("/reference")
async def list_reference(
    dataset: str | None = None,
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> dict:
    rows = await container.publications.list_reference(dataset)
    return {
        "items": [
            {
                "dataset": row.dataset,
                "period": row.period.isoformat(),
                "route": row.route,
                "metric": row.metric,
                "value": decimal_string(row.value),
                "file_name": row.file_name,
                "checksum": row.checksum,
            }
            for row in rows
        ],
        "meta": _meta(settings).model_dump(),
    }


@router.post("/backtest", response_model=BacktestResponse)
async def run_backtest(
    comparator: str = "dgca",
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> BacktestResponse:
    run = await container.publications.latest_run()
    published = await container.publications.series(series="headline", frequency=IndexFrequency.MONTHLY)
    reference = await container.publications.list_reference(comparator)
    result = compare_monthly(published, reference, comparator=comparator, run_id=None if run is None else run.id)
    stored = await container.publications.add_backtest(result)
    return BacktestResponse(
        id=stored.id,
        comparator=stored.comparator,
        status=stored.status.value,
        correlation=decimal_string(stored.correlation),
        mape=decimal_string(stored.mape),
        overlap_months=stored.overlap_months,
        notes=stored.notes,
        details=stored.details_json,
        meta=_meta(settings),
    )


@router.get("/backtest", response_model=BacktestResponse)
async def latest_backtest(
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> BacktestResponse:
    stored = await container.publications.latest_backtest()
    if stored is None:
        return BacktestResponse(
            comparator="none",
            status="unavailable",
            notes="No back-test has been run. Import a DGCA or CPI public file first.",
            meta=_meta(settings),
        )
    return BacktestResponse(
        id=stored.id,
        comparator=stored.comparator,
        status=stored.status.value,
        correlation=decimal_string(stored.correlation),
        mape=decimal_string(stored.mape),
        overlap_months=stored.overlap_months,
        notes=stored.notes,
        details=stored.details_json,
        meta=_meta(settings),
    )
