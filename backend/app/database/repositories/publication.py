from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apix_index.types import HeadlinePoint, IndexResult
from app.database.models.publication import (
    BacktestResult,
    BasketVersion,
    ElementaryCell,
    IndexRun,
    PublishedIndexValue,
    QualityCheck,
    ReferenceObservation,
    WeightVersion,
)
from app.domain.enums import BacktestStatus, IndexFrequency, IndexRunStatus, PublicationDisposition
from app.domain.hashing import sha256_canonical
from app.domain.models import utcnow


class PublicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_basket(self) -> BasketVersion | None:
        stmt = select(BasketVersion).order_by(BasketVersion.created_at.desc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def latest_weights(self) -> WeightVersion | None:
        stmt = select(WeightVersion).order_by(WeightVersion.created_at.desc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_basket(self, version: str) -> BasketVersion | None:
        stmt = select(BasketVersion).where(BasketVersion.version == version)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_weights(self, version: str) -> WeightVersion | None:
        stmt = select(WeightVersion).where(WeightVersion.version == version)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_basket(self, row: BasketVersion) -> BasketVersion:
        existing = await self.get_basket(row.version)
        if existing is not None:
            return existing
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_weights(self, row: WeightVersion) -> WeightVersion:
        existing = await self.get_weights(row.version)
        if existing is not None:
            return existing
        self.session.add(row)
        await self.session.flush()
        return row

    async def create_run(self, **kwargs) -> IndexRun:
        run = IndexRun(status=IndexRunStatus.RUNNING, started_at=utcnow(), **kwargs)
        self.session.add(run)
        await self.session.flush()
        return run

    async def complete_run(self, run: IndexRun, result: IndexResult, *, is_simulated: bool) -> IndexRun:
        coverage = result.headline[-1].coverage_pct if result.headline else Decimal("0")
        run.status = IndexRunStatus.COMPLETED
        run.completed_at = utcnow()
        run.output_hash = sha256_canonical(
            {
                "headline": [
                    {"period": point.period, "value": format(point.value, "f")} for point in result.headline
                ],
                "diagnostics": result.diagnostics,
            }
        )
        run.coverage_pct = coverage
        run.n_quotes = sum(point.n_quotes for point in result.headline)
        run.n_cells = int(result.diagnostics.get("n_cells_total") or 0)
        run.is_simulated = is_simulated
        run.diagnostics_json = result.diagnostics
        await self.session.flush()
        return run

    async def fail_run(self, run: IndexRun, message: str) -> IndexRun:
        run.status = IndexRunStatus.FAILED
        run.completed_at = utcnow()
        run.error_summary = message
        await self.session.flush()
        return run

    async def store_result(
        self,
        run: IndexRun,
        result: IndexResult,
        *,
        basket_version: str,
        weights_version: str,
        is_simulated: bool,
    ) -> None:
        for cell in result.cells:
            self.session.add(
                ElementaryCell(
                    run_id=run.id,
                    period=date.fromisoformat(cell.period),
                    route=cell.route,
                    carrier=cell.carrier,
                    apw_days=cell.apw_days,
                    matched=cell.matched,
                    laf=cell.laf,
                    availability=cell.availability,
                    adjusted=cell.adjusted,
                    n_matched=cell.n_matched,
                    n_quotes=cell.n_quotes,
                    suppressed=cell.suppressed,
                )
            )
        for point in result.headline:
            self.session.add(self._published(run, point, "headline", basket_version, weights_version, is_simulated))
        for row in result.by_apw:
            self.session.add(
                PublishedIndexValue(
                    run_id=run.id,
                    series="apw",
                    period=date.fromisoformat(row.period),
                    frequency=IndexFrequency.DAILY,
                    apw_days=row.apw_days,
                    value=row.value,
                    coverage_pct=row.coverage_pct,
                    n_matched=row.n_matched,
                    is_simulated=is_simulated,
                    method_version=result.method_version,
                    basket_version=basket_version,
                    weights_version=weights_version,
                    provenance_hash=run.output_hash or run.id.hex,
                )
            )
        for row in result.by_route:
            self.session.add(
                PublishedIndexValue(
                    run_id=run.id,
                    series="route",
                    period=date.fromisoformat(row.period),
                    frequency=IndexFrequency.DAILY,
                    route=row.route,
                    apw_days=row.apw_days,
                    value=row.value,
                    n_matched=row.n_matched,
                    is_simulated=is_simulated,
                    method_version=result.method_version,
                    basket_version=basket_version,
                    weights_version=weights_version,
                    provenance_hash=run.output_hash or run.id.hex,
                )
            )
        await self.session.flush()

    def _published(
        self,
        run: IndexRun,
        point: HeadlinePoint,
        series: str,
        basket_version: str,
        weights_version: str,
        is_simulated: bool,
        frequency: IndexFrequency = IndexFrequency.DAILY,
    ) -> PublishedIndexValue:
        return PublishedIndexValue(
            run_id=run.id,
            series=series,
            period=date.fromisoformat(point.period),
            frequency=frequency,
            value=point.value,
            se=point.se,
            ci_low=point.ci_low,
            ci_high=point.ci_high,
            coverage_pct=point.coverage_pct,
            n_matched=point.n_matched,
            is_simulated=is_simulated,
            method_version=run.method_version,
            basket_version=basket_version,
            weights_version=weights_version,
            provenance_hash=run.output_hash or run.id.hex,
        )

    async def store_frequency(
        self,
        run: IndexRun,
        points: list[HeadlinePoint],
        frequency: IndexFrequency,
        *,
        basket_version: str,
        weights_version: str,
        is_simulated: bool,
    ) -> None:
        for point in points:
            self.session.add(
                self._published(
                    run,
                    point,
                    "headline",
                    basket_version,
                    weights_version,
                    is_simulated,
                    frequency,
                )
            )
        await self.session.flush()

    async def add_quality(self, run_id: uuid.UUID | None, observation_id, code: str, disposition: PublicationDisposition, details: dict) -> None:
        self.session.add(
            QualityCheck(
                run_id=run_id,
                observation_id=observation_id,
                code=code,
                disposition=disposition,
                details=details,
            )
        )

    async def latest_run(self) -> IndexRun | None:
        stmt = (
            select(IndexRun)
            .where(IndexRun.status == IndexRunStatus.COMPLETED)
            .order_by(IndexRun.completed_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_run(self, run_id: uuid.UUID) -> IndexRun | None:
        return await self.session.get(IndexRun, run_id)

    async def series(
        self,
        *,
        series: str = "headline",
        frequency: IndexFrequency = IndexFrequency.DAILY,
        route: str | None = None,
        apw_days: int | None = None,
        run_id: uuid.UUID | None = None,
    ) -> list[PublishedIndexValue]:
        stmt = select(PublishedIndexValue).where(
            PublishedIndexValue.series == series,
            PublishedIndexValue.frequency == frequency,
        )
        if run_id is not None:
            stmt = stmt.where(PublishedIndexValue.run_id == run_id)
        else:
            latest = await self.latest_run()
            if latest is None:
                return []
            stmt = stmt.where(PublishedIndexValue.run_id == latest.id)
        if route:
            stmt = stmt.where(PublishedIndexValue.route == route)
        if apw_days is not None:
            stmt = stmt.where(PublishedIndexValue.apw_days == apw_days)
        stmt = stmt.order_by(PublishedIndexValue.period.asc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def cells(self, run_id: uuid.UUID, *, route: str | None = None) -> list[ElementaryCell]:
        stmt = select(ElementaryCell).where(ElementaryCell.run_id == run_id).order_by(ElementaryCell.period)
        if route:
            stmt = stmt.where(ElementaryCell.route == route)
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_reference(self, row: ReferenceObservation) -> ReferenceObservation:
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_reference(self, dataset: str | None = None) -> list[ReferenceObservation]:
        stmt = select(ReferenceObservation).order_by(ReferenceObservation.period)
        if dataset:
            stmt = stmt.where(ReferenceObservation.dataset == dataset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def add_backtest(self, row: BacktestResult) -> BacktestResult:
        self.session.add(row)
        await self.session.flush()
        return row

    async def latest_backtest(self) -> BacktestResult | None:
        stmt = select(BacktestResult).order_by(BacktestResult.computed_at.desc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_backtests(self, limit: int = 20) -> list[BacktestResult]:
        stmt = select(BacktestResult).order_by(BacktestResult.computed_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())
