import sqlite3
import json
import csv
import sys

db_file = sys.argv[1] if len(sys.argv) > 1 else 'apix-live-demo.db'
csv_file = sys.argv[2] if len(sys.argv) > 2 else 'fares_dump.csv'

conn = sqlite3.connect(db_file)
c = conn.cursor()
c.execute("SELECT record_json FROM raw_observations")
rows = c.fetchall()

if not rows:
    print(f"No records found in {db_file}")
    sys.exit(0)

records = [json.loads(row[0]) for row in rows]
keys = list(records[0].keys())

with open(csv_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=keys)
    writer.writeheader()
    writer.writerows(records)

print(f"Successfully dumped {len(records)} fares from {db_file} to {csv_file}")
