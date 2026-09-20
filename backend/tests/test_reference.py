from pathlib import Path

from app.backtesting.compare import compare_monthly
from app.domain.enums import BacktestStatus
from app.reference_data.checksum import sha256_file
from app.reference_data.dgca.loader import load_dgca_file


def test_dgca_loader_preserves_checksum(tmp_path: Path) -> None:
    path = tmp_path / "dgca.csv"
    path.write_text("period,route,fare\n2026-01-01,DEL-BOM,5400\n2026-02-01,DEL-BOM,5600\n", encoding="utf-8")
    checksum = sha256_file(path)
    rows = load_dgca_file(path, source_url="https://example.gov/dgca.csv")
    assert len(rows) == 2
    assert {row.checksum for row in rows} == {checksum}
    assert rows[0].source_url.endswith("dgca.csv")


def test_backtest_unavailable_without_official_file() -> None:
    result = compare_monthly([], [], comparator="dgca")
    assert result.status is BacktestStatus.UNAVAILABLE
    assert result.correlation is None


def test_backtest_not_reportable_with_short_overlap(tmp_path: Path) -> None:
    from datetime import date
    from decimal import Decimal

    from app.database.models.publication import PublishedIndexValue, ReferenceObservation
    from app.domain.enums import IndexFrequency

    published = [
        PublishedIndexValue(
            run_id=__import__("uuid").uuid4(),
            series="headline",
            period=date(2026, 1, 1),
            frequency=IndexFrequency.MONTHLY,
            value=Decimal("100"),
            n_matched=10,
            is_simulated=True,
            provenance_hash="0" * 64,
        )
    ]
    reference = [
        ReferenceObservation(
            dataset="dgca",
            period=date(2026, 1, 1),
            metric="average_fare",
            value=Decimal("5000"),
            file_name="dgca.csv",
            checksum="abc",
        )
    ]
    result = compare_monthly(published, reference, comparator="dgca")
    assert result.status is BacktestStatus.NOT_REPORTABLE
    assert result.overlap_months == 1
