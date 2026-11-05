"""FastAPI service exposing CostLens analytics and serving the dashboard."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from costlens import __version__, analytics
from costlens.pipeline import DuckDBStore, IngestError

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def create_app(store: DuckDBStore | None = None) -> FastAPI:
    app = FastAPI(title="CostLens API", version=__version__)
    app.state.store = store or DuckDBStore(os.getenv("COSTLENS_DB", "data/costlens.duckdb"))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("COSTLENS_CORS_ORIGINS", "*").split(","),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def rows() -> list[dict]:
        data = app.state.store.rows()
        if not data:
            raise HTTPException(status_code=404, detail="no cost data ingested yet")
        return data

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "service_days": app.state.store.count()}

    @app.get("/api/summary")
    def get_summary(period: int = Query(30, ge=1, le=365)) -> dict:
        return analytics.summary(rows(), period=period)

    @app.get("/api/daily")
    def get_daily(service: str | None = None) -> dict:
        return analytics.daily_series(rows(), service=service)

    @app.get("/api/anomalies")
    def get_anomalies(
        threshold: float = Query(4.0, ge=1.0, le=20.0),
        window: int = Query(28, ge=7, le=120),
        min_delta: float = Query(1.0, ge=0.0),
    ) -> dict:
        found = analytics.detect_anomalies(
            rows(), threshold=threshold, window=window, min_delta=min_delta
        )
        return {"threshold": threshold, "count": len(found), "anomalies": found}

    @app.get("/api/forecast")
    def get_forecast(lookback: int = Query(30, ge=7, le=180)) -> dict:
        return analytics.forecast_month(rows(), lookback=lookback)

    @app.post("/api/ingest", status_code=201)
    async def ingest(file: Annotated[UploadFile, File()]) -> dict:
        if not (file.filename or "").lower().endswith(".csv"):
            raise HTTPException(status_code=415, detail="upload a CUR export in CSV format")
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            shutil.copyfileobj(file.file, tmp)
            size = tmp.tell()
        try:
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="file exceeds 50 MB")
            try:
                n = app.state.store.ingest_csv(tmp.name)
            except IngestError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            os.unlink(tmp.name)
        return {"ingested_service_days": n, "total_service_days": app.state.store.count()}

    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
