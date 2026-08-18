"""
Fiscal Sentinel - FastAPI backend.

AI-powered financial intelligence for rural district councils. Exposes the
Python-computed risk scores, forecasts and briefs from analytics.py,
forecast.py and brief.py over HTTP for the React dashboard.

Positioning: most systems tell councils what happened. Fiscal Sentinel tells
them what needs attention next. Detected events are always "financial
anomalies" or "potential revenue leakage" - never "fraud".

Run (PowerShell, from backend/, with the venv active):
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from analytics import get_engine
from brief import generate_brief
from forecast import build_forecast


app = FastAPI(
    title="Fiscal Sentinel API",
    description=(
        "AI-powered financial intelligence for rural district councils. "
        "Detects revenue anomalies, forecasts collections, and explains "
        "risk in plain language."
    ),
    version="1.0.0",
)


# -------------------------------------------------------------------
# CORS
# -------------------------------------------------------------------
# Local React/Vite development servers.
#
# We will add the Vercel production URL here after deployment.
# -------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# Request Models
# -------------------------------------------------------------------

class BriefRequest(BaseModel):
    top_n: int = 5


# -------------------------------------------------------------------
# Root Endpoint
# -------------------------------------------------------------------

@app.get("/")
def root() -> dict[str, str]:
    """
    Basic API information.
    """
    return {
        "service": "Fiscal Sentinel API",
        "tagline": (
            "Most systems tell councils what happened. "
            "Fiscal Sentinel tells them what needs attention next."
        ),
        "docs": "/docs",
    }


# -------------------------------------------------------------------
# Health Endpoints
# -------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    """
    Detailed API health check.

    Confirms that the analytics engine can load and provides
    basic information about the financial dataset.
    """
    engine = get_engine()

    return {
        "status": "ok",
        "books_monitored": len(engine.books),
        "latest_period": engine.latest_period,
    }


@app.get("/health")
def health_check() -> dict[str, Any]:
    """
    Simple health endpoint for deployment platforms and monitoring.

    This is intentionally separate from /api/health so services such
    as Render, Vercel or external uptime monitors can easily check
    whether the API is alive.
    """
    engine = get_engine()

    return {
        "status": "healthy",
        "books_monitored": len(engine.books),
        "latest_period": engine.latest_period,
    }


# -------------------------------------------------------------------
# KPI Endpoint
# -------------------------------------------------------------------

@app.get("/api/kpis")
def kpis() -> dict[str, Any]:
    """
    Five headline KPI cards:

    - Revenue collected
    - Expected revenue
    - Revenue gap
    - Anomaly count
    - Next-quarter forecast
    """
    engine = get_engine()

    summary = engine.kpi_summary()
    fc = build_forecast(engine.df)

    return {
        "period_label": summary["period_label"],
        "revenue_this_month": summary["revenue_this_month"],
        "expected_this_month": summary["expected_this_month"],
        "revenue_gap": summary["revenue_gap"],
        "deviation_pct": summary["deviation_pct"],
        "month_on_month_pct": summary["month_on_month_pct"],
        "anomaly_count": summary["anomaly_count"],
        "critical_count": summary["critical_count"],
        "high_count": summary["high_count"],
        "watch_count": summary["watch_count"],
        "books_monitored": summary["books_monitored"],
        "exposure_identified": summary["exposure_identified"],
        "next_quarter_forecast": fc["district"]["forecast_total"],
        "next_quarter_budget": fc["district"]["budget_total"],
        "next_quarter_variance_pct": fc["district"]["variance_pct"],
        "forecast_window": fc["forecast_window"],
    }


# -------------------------------------------------------------------
# Anomaly Detection
# -------------------------------------------------------------------

@app.get("/api/anomalies")
def anomalies(min_score: float = 0.0) -> dict[str, Any]:
    """
    Financial Risk Radar.

    Returns all financial books ranked by risk score.
    """
    engine = get_engine()

    books = engine.radar()

    if min_score > 0:
        books = [
            b
            for b in books
            if b["risk_score"] >= min_score
        ]

    return {
        "count": len(books),
        "items": [
            {
                "id": b["id"],
                "ward": b["ward"],
                "revenue_stream": b["revenue_stream"],
                "collector_id": b["collector_id"],
                "risk_score": b["risk_score"],
                "risk_band": b["risk_band"],
                "headline": b["headline"],
                "deviation_pct": b["window_deviation_pct"],
                "revenue_gap": b["window_gap"],
                "seasonally_explained": b["seasonally_explained"],
            }
            for b in books
        ],
    }


# -------------------------------------------------------------------
# Individual Anomaly Details
# -------------------------------------------------------------------

@app.get("/api/anomalies/{book_id}")
def anomaly_detail(book_id: str) -> dict[str, Any]:
    """
    Returns detailed information about one financial anomaly,
    including its actual-vs-expected trend series.
    """
    engine = get_engine()

    detail = engine.detail(book_id)

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"No book found with id '{book_id}'",
        )

    return detail


# -------------------------------------------------------------------
# District Forecast
# -------------------------------------------------------------------

@app.get("/api/forecast")
def forecast() -> dict[str, Any]:
    """
    District-wide and per-stream three-month revenue forecast
    compared against budget.
    """
    engine = get_engine()

    return build_forecast(engine.df)


# -------------------------------------------------------------------
# Revenue Stream Forecast
# -------------------------------------------------------------------

@app.get("/api/forecast/{revenue_stream}")
def forecast_stream(revenue_stream: str) -> dict[str, Any]:
    """
    Returns a forecast for a specific revenue stream.
    """
    engine = get_engine()

    fc = build_forecast(engine.df)

    for stream in fc["streams"]:
        if stream["revenue_stream"].lower() == revenue_stream.lower():
            return stream

    raise HTTPException(
        status_code=404,
        detail=(
            f"No revenue stream found matching "
            f"'{revenue_stream}'"
        ),
    )


# -------------------------------------------------------------------
# AI Financial Brief
# -------------------------------------------------------------------

@app.post("/api/brief")
def brief(req: BriefRequest | None = None) -> dict[str, Any]:
    """
    Generate an executive financial brief based on
    the current analytical findings.
    """
    top_n = req.top_n if req else 5

    result = generate_brief(top_n=top_n)

    return {
        "source": result["source"],
        "model": result["model"],
        "brief": result["brief"],
        "note": result["note"],
    }


# -------------------------------------------------------------------
# Local Development Entry Point
# -------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )