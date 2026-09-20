FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
COPY apix_index /app/apix_index
COPY config /app/config
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

RUN pip install --upgrade pip && pip install .

FROM base AS worker
RUN pip install ".[live]" && playwright install --with-deps chromium
CMD ["python", "-m", "app.worker.runner"]

FROM base AS api
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
