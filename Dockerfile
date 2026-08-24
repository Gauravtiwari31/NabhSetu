FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src APIX_DB=/app/data/apix.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data

EXPOSE 8000
# The image ships empty. `docker compose run --rm apix python cli.py demo-seed`
# or run init/backfill/index once, then the API serves from the mounted volume.
CMD ["python", "cli.py", "serve", "--host", "0.0.0.0", "--port", "8000"]
