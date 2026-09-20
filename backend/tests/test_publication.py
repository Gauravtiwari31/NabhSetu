from app.domain.enums import CollectionStatus
from app.services.seeding import MOCK_SOURCE_ID
from tests.conftest import make_query


async def test_publication_run_from_mock_quotes(container) -> None:
    query = make_query(source_id=MOCK_SOURCE_ID)
    _job_id, result = await container.collection.submit(query, request_id="pub-1")
    await container.sources.session.commit()
    assert result.status is CollectionStatus.SUCCESS
    published = await container.publisher.publish(bootstrap_draws=0, n_min=1, apply_dow_smoothing=False)
    await container.sources.session.commit()
    assert published.headline
    assert published.method_version == "1.0.0"
    latest = await container.publications.latest_run()
    assert latest is not None
    assert latest.is_simulated is True
