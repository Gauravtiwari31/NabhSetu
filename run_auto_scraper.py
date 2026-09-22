import asyncio
import os
import json
import csv
from datetime import date, timedelta
from pathlib import Path
import time
import sys

# Append backend to path so 'app' imports work
sys.path.insert(0, os.path.abspath('backend'))

# Force load from .env ignoring poisoned shell variables
from dotenv import load_dotenv
load_dotenv(override=True)

from app.acquisition.orchestrator import LiveRunOrchestrator
from app.config.settings import get_settings
from app.database.session import create_engine_from_settings, create_session_factory
from app.services.container import build_container
from app.services.seeding import seed_if_needed

ROUTES = [("DEL", "BOM"), ("BOM", "BLR"), ("DEL", "BLR")]

def append_to_csv(records, filename="live_fares.csv"):
    """Append this cycle's fares to the CSV export.

    The header is taken from the union of every row's keys, not from the first
    row, so an optional field that happens to be absent from the first fare
    cannot silently drop that column for the whole file. If the file already
    exists with a different header, the rows go to a new timestamped file
    rather than being written under the wrong columns -- an append that
    silently misaligns is worse than a second file.
    """
    if not records:
        return

    all_fares = []
    for r in records:
        if r.status == 'success' and hasattr(r, 'fares'):
            all_fares.extend(r.fares)

    if not all_fares:
        return

    fieldnames = list(dict.fromkeys(k for row in all_fares for k in row))

    if os.path.isfile(filename):
        with open(filename, 'r', newline='', encoding='utf-8') as f:
            existing = next(csv.reader(f), None)
        if existing and existing != fieldnames:
            stamp = time.strftime('%Y%m%dT%H%M%S')
            filename = f"{os.path.splitext(filename)[0]}_{stamp}.csv"
            print(f"--> Export schema changed; writing to {filename} instead")

    file_exists = os.path.isfile(filename)
    with open(filename, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        writer.writerows(all_fares)
    print(f"--> Saved {len(all_fares)} individual fares to {filename}")

async def run_cycle():
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    browser = None
    
    print("\n=======================================================", flush=True)
    print(f"Starting Scraping Cycle at {time.strftime('%X')}", flush=True)
    print("=======================================================", flush=True)
    
    try:
        async with factory() as session:
            await seed_if_needed(session)
            container = build_container(session, settings)
            browser = container.browser
            
            # The orchestrator automatically fetches fares and inserts them into the Render Postgres DB
            records = await LiveRunOrchestrator(container).run(
                routes=ROUTES,
                observation_date=date.today()
            )
            
            total_fares = sum(len(r.fares) for r in records if hasattr(r, 'fares'))
            print(f"Cycle finished! Extracted {total_fares} fares and PUSHED to Render Website.")
            append_to_csv(records, "live_fares.csv")
            return records
    except Exception as e:
        import traceback
        print(f"Error during scraping cycle:")
        traceback.print_exc()
    finally:
        if browser is not None:
            await browser.close()
        await engine.dispose()

def main():
    print("Starting Nabhsetu Automated Scraper Background Task...")
    print("This will run every 3 hours, scrape live fares, update the Render Database, and save to live_fares.csv")
    while True:
        asyncio.run(run_cycle())
        print("\nWaiting 3 hours before next run... (Leave this terminal open!)")
        time.sleep(10800)  # Sleep for 3 hours

if __name__ == "__main__":
    main()
