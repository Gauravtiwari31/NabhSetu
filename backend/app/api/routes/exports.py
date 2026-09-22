import csv
import io
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, Response

from app.api.deps import get_container, get_settings, require_api_key
from app.config import Settings
from app.domain.enums import IndexFrequency
from app.services.container import AppContainer

router = APIRouter(prefix="/v1/exports", tags=["exports"], dependencies=[Depends(require_api_key)])


@router.get("/index.csv")
async def export_csv(
    frequency: IndexFrequency = Query(default=IndexFrequency.DAILY),
    series: str = Query(default="headline"),
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    rows = await container.publications.series(series=series, frequency=frequency)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "period",
            "value",
            "se",
            "ci_low",
            "ci_high",
            "coverage_pct",
            "route",
            "apw_days",
            "is_simulated",
            "method_version",
            "data_mode",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.period.isoformat(),
                format(row.value, "f"),
                "" if row.se is None else format(row.se, "f"),
                "" if row.ci_low is None else format(row.ci_low, "f"),
                "" if row.ci_high is None else format(row.ci_high, "f"),
                "" if row.coverage_pct is None else format(row.coverage_pct, "f"),
                row.route or "",
                "" if row.apw_days is None else row.apw_days,
                row.is_simulated,
                row.method_version,
                settings.data_mode.value,
            ]
        )
    return PlainTextResponse(buffer.getvalue(), media_type="text/csv")


@router.get("/index.sdmx.json")
async def export_sdmx(
    frequency: IndexFrequency = Query(default=IndexFrequency.DAILY),
    container: AppContainer = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> Response:
    rows = await container.publications.series(series="headline", frequency=frequency)
    payload = {
        "meta": {
            "id": "APIX-T",
            "agencyID": "MOSPI",
            "version": "1.0.0",
            "is_simulated": settings.data_mode.value == "mock" or any(row.is_simulated for row in rows),
            "data_mode": settings.data_mode.value,
        },
        "data": {
            "dataSets": [
                {
                    "action": "Replace",
                    "series": {
                        str(index): {
                            "observations": {row.period.isoformat(): [format(row.value, "f")]}
                        }
                        for index, row in enumerate(rows)
                    },
                }
            ],
            "structure": {
                "name": "APIx-T Airfare Price Index",
                "dimensions": {
                    "observation": [{"id": "TIME_PERIOD", "values": [{"id": row.period.isoformat()} for row in rows]}]
                },
            },
        },
    }
    return Response(json.dumps(payload), media_type="application/vnd.sdmx.data+json")
