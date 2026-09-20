from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.main import create_app
from app.services.seeding import MOCK_SOURCE_ID


def _client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


def test_health_labels_mock_mode() -> None:
    with _client() as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["data_mode"] == "mock"
        assert body["is_simulated"] is True
        assert "simulated" in (body["notice"] or "").lower()


def test_sources_endpoint_lists_mock_source() -> None:
    with _client() as client:
        response = client.get("/sources", headers={"X-API-Key": "test-api-key"})
        assert response.status_code == 200
        items = response.json()["items"]
        names = [item["name"] for item in items]
        assert "MockFareSource" in names
        mock = next(item for item in items if item["name"] == "MockFareSource")
        assert mock["enabled"] is True
        assert mock["automation_allowed"] is True


def test_live_mode_disables_mock_and_exposes_policy_fields(monkeypatch) -> None:
    monkeypatch.setenv("APIX_DATA_MODE", "live")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.get("/sources", headers={"X-API-Key": "test-api-key"})
            assert response.status_code == 200
            items = {item["name"]: item for item in response.json()["items"]}
            assert items["MockFareSource"]["enabled"] is False
            assert items["EaseMyTrip"]["automation_allowed"] is True
            assert items["EaseMyTrip"]["terms_review_status"] == "approved"
            assert items["MakeMyTrip"]["automation_allowed"] is False
            assert items["MakeMyTrip"]["terms_review_status"] == "denied"
    finally:
        monkeypatch.setenv("APIX_DATA_MODE", "mock")
        get_settings.cache_clear()


def test_collection_job_requires_api_key() -> None:
    with _client() as client:
        response = client.post(
            "/collection-jobs",
            json={"origin": "DEL", "destination": "BOM", "lead_time_days": 7},
        )
        assert response.status_code == 401


def test_collection_job_and_latest_fares() -> None:
    with _client() as client:
        response = client.post(
            "/collection-jobs",
            headers={"X-API-Key": "test-api-key"},
            json={
                "origin": "DEL",
                "destination": "BOM",
                "observation_date": "2026-09-20",
                "travel_date": "2026-09-27",
                "lead_time_days": 7,
                "source_id": str(MOCK_SOURCE_ID),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["is_simulated"] is True
        assert body["result_status"] == "success"
        assert body["observation_ids"]
        assert body["provenance"]
        job = client.get(f"/collection-jobs/{body['id']}", headers={"X-API-Key": "test-api-key"})
        assert job.status_code == 200
        fares = client.get(
            "/fares/latest",
            params={"origin": "DEL", "destination": "BOM"},
            headers={"X-API-Key": "test-api-key"},
        )
        assert fares.status_code == 200
        payload = fares.json()
        assert payload["items"]
        assert payload["meta"]["is_simulated"] is True
        status = client.get(f"/sources/{MOCK_SOURCE_ID}/status", headers={"X-API-Key": "test-api-key"})
        assert status.status_code == 200
        assert status.json()["name"] == "MockFareSource"
