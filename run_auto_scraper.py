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

# Set env vars to connect to Render and enable Live mode
os.environ.setdefault("APIX_DATA_MODE", "live")
os.environ.setdefault("APIX_DATABASE_URL", "postgresql://<YOUR_USER>:<YOUR_PASSWORD>@<YOUR_HOST>/<YOUR_DB>")
os.environ.setdefault("APIX_API_KEY", "change-me")

from app.acquisition.orchestrator import LiveRunOrchestrator
from app.config.settings import get_settings
from app.database.session import create_engine_from_settings, create_session_factory
from app.services.container import build_container
from app.services.seeding import seed_if_needed

ROUTES = [("DEL", "BOM"), ("BOM", "BLR"), ("DEL", "BLR")]

def append_to_csv(records, filename="live_fares.csv"):
    if not records:
        return
    
    file_exists = os.path.isfile(filename)
    
    all_fares = []
    for r in records:
        if r.status == 'success' and hasattr(r, 'fares'):
            for fare_dict in r.fares:
                all_fares.append(fare_dict)
    
    if not all_fares:
        return
        
    with open(filename, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(all_fares[0].keys()))
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
        print(f"Error during scraping cycle: {e}")
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
