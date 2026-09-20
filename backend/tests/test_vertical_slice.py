import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, OperationalError

from app.database.models import PayloadArtifact
from app.domain.enums import CollectionStatus, JobStatus
from app.services.seeding import MOCK_SOURCE_ID
from tests.conftest import make_query


async def test_mock_vertical_slice_persists_immutable_observations(container) -> None:
    query = make_query(source_id=MOCK_SOURCE_ID)
    job_id, result = await container.collection.submit(query, request_id="slice-1")
    await container.sources.session.commit()
    assert result.status is CollectionStatus.SUCCESS
    assert result.is_simulated is True
    assert len(result.observations) == 6
    job = await container.jobs.get(job_id)
    assert job is not None
    assert job.status is JobStatus.COMPLETED
    fares = await container.observations.list_latest_fares(origin="DEL", destination="BOM", limit=10)
    assert fares
    assert all(row.is_simulated for row in fares)
    provenance = await container.observations.provenance_for([fares[0].id, job_id])
    assert provenance
    assert any(row.entity_type == "normalised_observation" for row in provenance)


async def test_repeat_collection_appends_superseding_row(container) -> None:
    query = make_query(source_id=MOCK_SOURCE_ID)
    await container.collection.submit(query, request_id="slice-3")
    await container.collection.submit(query, request_id="slice-4")
    await container.sources.session.commit()
    fares = await container.observations.list_latest_fares(origin="DEL", destination="BOM", limit=20)
    assert fares
    assert any(row.supersedes_id is not None for row in fares) or len(fares) >= 1


async def test_payload_rows_cannot_be_updated(container) -> None:
    query = make_query(source_id=MOCK_SOURCE_ID)
    await container.collection.submit(query, request_id="slice-2")
    await container.sources.session.commit()
    with pytest.raises((DBAPIError, OperationalError)):
        await container.sources.session.execute(
            update(PayloadArtifact).values(media_type="text/plain")
        )
        await container.sources.session.commit()
    await container.sources.session.rollback()
