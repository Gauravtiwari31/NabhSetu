from __future__ import annotations

from app.acquisition.base import BaseCollector
from app.config import DataMode, Settings
from app.domain.enums import CollectionStatus, CollectorModality, SourceType
from app.domain.models import CollectionResult, SourceProfile, utcnow


class DocumentCollector(BaseCollector):
    identity = CollectorModality.DOCUMENT
    parser_name = "airline_document"
    parser_version = "1.0.0"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def supports(self, source: SourceProfile) -> bool:
        return (
            self.settings.data_mode == DataMode.LIVE
            and source.source_type != SourceType.MOCK
            and source.capabilities.documents_available
        )

    async def collect(self, query, source, *, lease, egress) -> CollectionResult:
        started = utcnow()
        return CollectionResult(
            source_id=source.id,
            collector=self.identity,
            status=CollectionStatus.UNSUPPORTED,
            requested_at=started,
            completed_at=utcnow(),
            metadata={"reason": "no_document_parser_for_source"},
        )


class VisualCollector(BaseCollector):
    identity = CollectorModality.VISUAL
    parser_name = "airline_visual"
    parser_version = "1.0.0"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def supports(self, source: SourceProfile) -> bool:
        return False

    async def collect(self, query, source, *, lease, egress) -> CollectionResult:
        started = utcnow()
        return CollectionResult(
            source_id=source.id,
            collector=self.identity,
            status=CollectionStatus.UNSUPPORTED,
            requested_at=started,
            completed_at=utcnow(),
            metadata={"reason": "visual_adapter_disabled"},
        )
