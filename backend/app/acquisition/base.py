from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.enums import CollectorModality
from app.domain.models import (
    CollectionResult,
    ComplianceLease,
    EgressSelection,
    FareQuery,
    SourceProfile,
)


class BaseCollector(ABC):
    """Shared collector contract. Implementations never open unrestricted clients."""

    identity: CollectorModality
    parser_name: str
    parser_version: str

    @abstractmethod
    async def supports(self, source: SourceProfile) -> bool:
        """Return True when this collector may be offered for the source."""

    @abstractmethod
    async def collect(
        self,
        query: FareQuery,
        source: SourceProfile,
        *,
        lease: ComplianceLease,
        egress: EgressSelection | None,
    ) -> CollectionResult:
        """Collect a fare observation or a typed failure result."""
