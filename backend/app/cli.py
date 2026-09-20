"""Operational CLI for file imports, index publication, and back-tests."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.config import get_settings
from app.database.session import create_engine_from_settings, create_session_factory
from app.reference_data.cpi.loader import load_cpi_file
from app.reference_data.dgca.loader import load_dgca_file
from app.services.container import build_container
from app.services.seeding import seed_if_needed


async def _session():
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_if_needed(session)
        yield settings, session, engine
    await engine.dispose()


async def cmd_import_dgca(path: str, source_url: str | None) -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_if_needed(session)
        container = build_container(session, settings)
        rows = load_dgca_file(Path(path), source_url=source_url)
        for row in rows:
            await container.publications.add_reference(row)
        await session.commit()
        print(f"imported {len(rows)} DGCA rows from {path}")
    await engine.dispose()


async def cmd_import_cpi(path: str, source_url: str | None) -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_if_needed(session)
        container = build_container(session, settings)
        rows = load_cpi_file(Path(path), source_url=source_url)
        for row in rows:
            await container.publications.add_reference(row)
        await session.commit()
        print(f"imported {len(rows)} CPI rows from {path}")
    await engine.dispose()


async def cmd_run_index() -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_if_needed(session)
        container = build_container(session, settings)
        result = await container.publisher.publish()
        await session.commit()
        latest = result.headline[-1]
        print(f"published {len(result.headline)} periods; latest {latest.period}={latest.value}")
    await engine.dispose()


async def cmd_backtest(comparator: str) -> None:
    from app.backtesting.compare import compare_monthly
    from app.domain.enums import IndexFrequency

    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_if_needed(session)
        container = build_container(session, settings)
        run = await container.publications.latest_run()
        published = await container.publications.series(series="headline", frequency=IndexFrequency.MONTHLY)
        reference = await container.publications.list_reference(comparator)
        result = compare_monthly(published, reference, comparator=comparator, run_id=None if run is None else run.id)
        await container.publications.add_backtest(result)
        await session.commit()
        print(f"{result.comparator} {result.status.value}: {result.notes}")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="apix")
    sub = parser.add_subparsers(dest="command", required=True)
    dgca = sub.add_parser("import-dgca")
    dgca.add_argument("path")
    dgca.add_argument("--source-url")
    cpi = sub.add_parser("import-cpi")
    cpi.add_argument("path")
    cpi.add_argument("--source-url")
    sub.add_parser("run-index")
    back = sub.add_parser("backtest")
    back.add_argument("--comparator", default="dgca")
    args = parser.parse_args()
    if args.command == "import-dgca":
        asyncio.run(cmd_import_dgca(args.path, args.source_url))
    elif args.command == "import-cpi":
        asyncio.run(cmd_import_cpi(args.path, args.source_url))
    elif args.command == "run-index":
        asyncio.run(cmd_run_index())
    elif args.command == "backtest":
        asyncio.run(cmd_backtest(args.comparator))


if __name__ == "__main__":
    main()
