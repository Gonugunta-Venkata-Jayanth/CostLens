# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COSTLENS_DB=/app/data/costlens.duckdb

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY costlens ./costlens
COPY api ./api
COPY frontend ./frontend

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

# Seed synthetic data on first start so the dashboard is usable immediately.
CMD ["sh", "-c", "python -m costlens seed --if-empty && uvicorn api.main:app --host 0.0.0.0 --port 8000"]
