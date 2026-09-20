from app.config.settings import DataMode, EgressMode, Settings


def test_defaults_are_mock_and_direct(monkeypatch) -> None:
    monkeypatch.delenv("APIX_DATA_MODE", raising=False)
    monkeypatch.delenv("APIX_EGRESS_MODE", raising=False)
    monkeypatch.delenv("APIX_DATABASE_URL", raising=False)
    monkeypatch.delenv("APIX_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.data_mode is DataMode.MOCK
    assert settings.egress_mode is EgressMode.DIRECT
    assert settings.database_url is None
    assert settings.api_key is None


def test_scheduler_source_allowlist_parses_csv() -> None:
    settings = Settings(_env_file=None, scheduler_source_names="EaseMyTrip, AkasaAir")
    assert settings.scheduler_source_allowlist() == ("EaseMyTrip", "AkasaAir")
