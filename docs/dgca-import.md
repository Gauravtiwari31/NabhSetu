# DGCA / CPI import

Official series are never invented. Operators download a public file and import
it with checksum provenance.

CSV columns recognised:

- period / month / date
- route / sector / city_pair (optional)
- fare / yield / avg_fare / cpi / index / value
- metric / series (optional)
- carrier / airline (optional, used only for traffic-derived weights)

```bash
python -m app.cli import-dgca downloaded.csv --source-url https://www.dgca.gov.in/...
python -m app.cli import-cpi downloaded.csv --source-url https://www.mospi.gov.in/...
```

Each stored row keeps `file_name`, `checksum`, `source_url`, and the raw record.
Missing files return HTTP 404 / CLI errors; they do not synthesise values.

Traffic rows with metric `passengers` / `traffic` / `pax` can generate a
`WeightSet` via `app.reference_data.weights.weights_from_traffic`. Equal seed
weights in `backend/config/weights.yaml` remain in force until that import.
