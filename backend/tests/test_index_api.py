from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.main import create_app
from app.services.seeding import MOCK_SOURCE_ID


def _client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


def test_sensitive_gets_require_api_key() -> None:
    with _client() as client:
        assert client.get("/sources").status_code == 401
        assert client.get("/fares/latest").status_code == 401
        assert client.get("/v1/index").status_code == 401


def test_mock_pipeline_publishes_labelled_index() -> None:
    headers = {"X-API-Key": "test-api-key"}
    with _client() as client:
        collected = client.post(
            "/collection-jobs",
            headers=headers,
            json={
                "origin": "DEL",
                "destination": "BOM",
                "observation_date": "2026-09-20",
                "travel_date": "2026-09-27",
                "lead_time_days": 7,
                "source_id": str(MOCK_SOURCE_ID),
            },
        )
        assert collected.status_code == 200, collected.text
        assert collected.json()["is_simulated"] is True
        published = client.post("/v1/index/publish", headers=headers)
        assert published.status_code in {200, 409}, published.text
        series = client.get("/v1/index", headers=headers)
        assert series.status_code == 200
        body = series.json()
        assert body["meta"]["is_simulated"] is True
        methodology = client.get("/v1/methodology", headers=headers)
        assert methodology.status_code == 200
        assert methodology.json()["method_version"] == "1.0.0"
        backtest = client.get("/v1/backtest", headers=headers)
        assert backtest.status_code == 200
        assert backtest.json()["status"] in {"unavailable", "not_reportable", "reportable"}
        csv_body = client.get("/v1/exports/index.csv", headers=headers)
        assert csv_body.status_code == 200
        sdmx = client.get("/v1/exports/index.sdmx.json", headers=headers)
        assert sdmx.status_code == 200
