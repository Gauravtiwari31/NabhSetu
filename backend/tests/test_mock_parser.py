import pytest

from app.domain.enums import CollectionStatus
from app.services.seeding import MOCK_SOURCE_ID
from app.sources.mock_fare.normaliser import normalise_observation
from app.sources.mock_fare.parser import MockParseError, load_fixture, parse_records
from tests.conftest import make_query


async def test_valid_fixture_parses_six_fares(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    rows = parse_records(load_fixture("valid.json"), make_query(), source)
    assert len(rows) == 6
    assert rows[0].carrier == "6E"
    assert rows[0].is_simulated is True
    assert rows[0].total_fare == rows[0].components().total_fare


async def test_missing_fields_are_null_not_invented(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    rows = parse_records(load_fixture("missing_fields.json"), make_query(), source)
    assert rows[0].base_fare is None
    assert rows[0].taxes is None
    assert rows[0].total_fare is not None


async def test_changed_layout_is_source_changed(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    with pytest.raises(MockParseError) as exc:
        parse_records(load_fixture("changed_layout.json"), make_query(), source)
    assert exc.value.status is CollectionStatus.SOURCE_CHANGED


async def test_invalid_negative_fare_is_rejected(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    with pytest.raises(MockParseError) as exc:
        parse_records(load_fixture("invalid.json"), make_query(), source)
    assert exc.value.status is CollectionStatus.INVALID_DATA


async def test_normaliser_uppercases_identifiers(container) -> None:
    source = await container.sources.get(MOCK_SOURCE_ID)
    observation = parse_records(load_fixture("valid.json"), make_query(), source)[0]
    observation.origin_airport = "del"
    normalised = normalise_observation(observation)
    assert normalised.origin_airport == "DEL"
    assert normalised.duplicate_key
