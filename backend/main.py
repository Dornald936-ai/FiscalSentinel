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

# CORS for the local React dev server (Vite default 5173, CRA default 3000).
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


class BriefRequest(BaseModel):
    top_n: int = 5


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "Fiscal Sentinel API",
        "tagline": "Most systems tell councils what happened. "
                   "Fiscal Sentinel tells them what needs attention next.",
        "docs": "/docs",
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    engine = get_engine()
    return {
        "status": "ok",
        "books_monitored": len(engine.books),
        "latest_period": engine.latest_period,
    }


@app.get("/api/kpis")
def kpis() -> dict[str, Any]:
    """Five headline KPI cards: revenue, expected, gap, anomaly count, next-quarter forecast."""
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


@app.get("/api/anomalies")
def anomalies(min_score: float = 0.0) -> dict[str, Any]:
    """Financial Risk Radar: every book, highest risk first, with its risk score."""
    engine = get_engine()
    books = engine.radar()
    if min_score > 0:
        books = [b for b in books if b["risk_score"] >= min_score]

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


@app.get("/api/anomalies/{book_id}")
def anomaly_detail(book_id: str) -> dict[str, Any]:
    """A single anomaly's full detail, including its actual-vs-expected trend series."""
    engine = get_engine()
    detail = engine.detail(book_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No book found with id '{book_id}'")
    return detail


@app.get("/api/forecast")
def forecast() -> dict[str, Any]:
    """District-wide and per-stream 3-month forecast against budget."""
    engine = get_engine()
    return build_forecast(engine.df)


@app.get("/api/forecast/{revenue_stream}")
def forecast_stream(revenue_stream: str) -> dict[str, Any]:
    """Forecast series for a single revenue stream."""
    engine = get_engine()
    fc = build_forecast(engine.df)
    for s in fc["streams"]:
        if s["revenue_stream"].lower() == revenue_stream.lower():
            return s
    raise HTTPException(
        status_code=404,
        detail=f"No revenue stream found matching '{revenue_stream}'",
    )


@app.post("/api/brief")
def brief(req: BriefRequest | None = None) -> dict[str, Any]:
    """Generate the executive financial brief from current findings."""
    top_n = req.top_n if req else 5
    result = generate_brief(top_n=top_n)
    return {
        "source": result["source"],
        "model": result["model"],
        "brief": result["brief"],
        "note": result["note"],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
