from datetime import date
from types import SimpleNamespace

from app.acquisition.scheduler import QueryScheduler
from app.config.settings import DataMode, Settings
from app.domain.enums import SourceType
from app.worker.scheduler import select_scheduled_sources


def test_scheduler_expands_official_lead_times() -> None:
    queries = QueryScheduler().expand(
        origin="DEL",
        destination="BOM",
        observation_date=date(2026, 9, 20),
    )
    assert [item.lead_time_days for item in queries] == [1, 7, 15, 30, 45]
    assert queries[0].travel_date.isoformat() == "2026-09-21"
    assert queries[-1].travel_date.isoformat() == "2026-11-04"


def _profile(**kwargs):
    defaults = {
        "name": "EaseMyTrip",
        "source_type": SourceType.OTA,
        "enabled": True,
        "automation_allowed": True,
        "temporarily_blocked": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_select_scheduled_sources_live_skips_mock_and_denied() -> None:
    settings = Settings(_env_file=None, data_mode=DataMode.LIVE, scheduler_source_names="")
    selected = select_scheduled_sources(
        [
            _profile(name="MockFareSource", source_type=SourceType.MOCK),
            _profile(name="MakeMyTrip", automation_allowed=False),
            _profile(name="EaseMyTrip"),
            _profile(name="AkasaAir", source_type=SourceType.AIRLINE),
        ],
        settings,
    )
    assert [item.name for item in selected] == ["EaseMyTrip", "AkasaAir"]


def test_select_scheduled_sources_honours_allowlist() -> None:
    settings = Settings(
        _env_file=None,
        data_mode=DataMode.LIVE,
        scheduler_source_names="EaseMyTrip",
    )
    selected = select_scheduled_sources(
        [_profile(name="EaseMyTrip"), _profile(name="AkasaAir", source_type=SourceType.AIRLINE)],
        settings,
    )
    assert [item.name for item in selected] == ["EaseMyTrip"]


def test_select_scheduled_sources_mock_mode_only_mock() -> None:
    settings = Settings(_env_file=None, data_mode=DataMode.MOCK)
    selected = select_scheduled_sources(
        [
            _profile(name="MockFareSource", source_type=SourceType.MOCK),
            _profile(name="EaseMyTrip"),
        ],
        settings,
    )
    assert [item.name for item in selected] == ["MockFareSource"]
