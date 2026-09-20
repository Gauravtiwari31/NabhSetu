from app.domain.enums import JobStatus
from app.services.seeding import MOCK_SOURCE_ID
from tests.conftest import make_query


async def test_worker_claim_pending_executes_mock_job(container) -> None:
    query = make_query(source_id=MOCK_SOURCE_ID)
    job_id = await container.collection.enqueue(query, request_id="queue-1")
    await container.sources.session.commit()
    claimed = await container.jobs.claim_pending()
    assert claimed is not None
    assert claimed.id == job_id
    result = await container.collection.execute(claimed, query, request_id="queue-1")
    await container.sources.session.commit()
    assert result.is_simulated is True
    stored = await container.jobs.get(job_id)
    assert stored is not None
    assert stored.status is JobStatus.COMPLETED


async def test_second_claim_finds_nothing_when_queue_empty(container) -> None:
    assert await container.jobs.claim_pending() is None
