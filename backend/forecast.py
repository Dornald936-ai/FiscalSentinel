"""
Fiscal Sentinel - three-month collection forecast per revenue stream.

Method
------
Each stream carries a strong annual profile (licences renew in January, markets
peak in December), and 18 months of history is not enough to fit a seasonal
Holt-Winters model directly. So seasonality is taken from the council's own
budget profile, which is exactly what `expected_revenue` encodes:

  1. Fit log(expected) ~ t per stream to recover the underlying growth trend.
  2. Seasonal index for each calendar month = median(expected / trend).
  3. Deseasonalise the *actual* collections with those indices - what is left is
     the council's underlying collection performance.
  4. Fit a damped additive-trend exponential smoothing model (statsmodels) to
     that deseasonalised series and project three months ahead.
  5. Re-apply the seasonal index, and widen a residual-based interval with the
     forecast horizon to give the confidence range.
  6. Project the budget line forward the same way and report the variance.

Damping keeps an 18-point series from extrapolating a short-run slope off the
chart, which matters when a stream has just had an anomalous month.

Run:
    python backend/forecast.py
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from analytics import load_data, money

HORIZON = 3          # months to forecast
Z_95 = 1.96          # confidence multiplier for the range
MIN_INTERVAL_PCT = 0.04   # never show a range tighter than +/-4%

warnings.simplefilter("ignore", ConvergenceWarning)
warnings.simplefilter("ignore", RuntimeWarning)


def _period_label(period: pd.Period) -> str:
    return period.strftime("%b %y")


def seasonal_profile(expected: pd.Series, periods: pd.PeriodIndex) -> tuple[np.ndarray, float, float]:
    """Recover (seasonal index by calendar month, base level, monthly growth).

    Growth is measured from year-on-year pairs of the *same* calendar month, not
    by regressing on t. An 18-month window contains January to June twice and
    July to December once, so a naive trend fit is dragged around by whichever
    half of the year happens to be over-represented - which for a stream like
    Business Licenses (a 2.35x January renewal peak seen twice) turns real
    growth into a large phantom decline.
    """
    values = expected.to_numpy(dtype=float)
    t = np.arange(len(values), dtype=float)

    # --- growth: compare each month to the same month a year earlier ---
    by_period = {str(p): v for p, v in zip(periods, values)}
    ratios = [
        by_period[str(p)] / by_period[str(p - 12)]
        for p in periods
        if str(p - 12) in by_period and by_period[str(p - 12)] > 0
    ]
    if ratios:
        annual_growth = float(np.median(ratios))
        monthly_growth = annual_growth ** (1.0 / 12.0) - 1.0
    else:
        # Under a year of history: fall back to a log-linear slope.
        slope, _ = np.polyfit(t, np.log(np.maximum(values, 1e-9)), 1)
        monthly_growth = float(np.exp(slope) - 1.0)

    # --- seasonality: detrend, then take the median level per calendar month ---
    detrended = values / (1.0 + monthly_growth) ** t

    raw_index = np.zeros(13)
    for month in range(1, 13):
        mask = periods.month == month
        raw_index[month] = float(np.median(detrended[mask])) if mask.any() else np.nan

    observed = raw_index[1:][np.isfinite(raw_index[1:])]
    base_level = float(np.mean(observed)) if observed.size else float(np.mean(detrended))
    if base_level <= 0:
        base_level = float(np.mean(detrended)) or 1.0

    index = np.ones(13)
    for month in range(1, 13):
        index[month] = raw_index[month] / base_level if np.isfinite(raw_index[month]) else 1.0

    return index, base_level, float(monthly_growth)


def damp_isolated_outliers(series: np.ndarray, threshold: float = 2.5) -> tuple[np.ndarray, int]:
    """Pull in one-off spikes so they do not drag the forecast level.

    A month is only damped if it is extreme *and* its neighbours are not. A run
    of consecutive extreme months is a genuine level shift - exactly what
    sustained revenue leakage looks like - and must survive into the forecast.
    """
    s = np.array(series, dtype=float)
    med = float(np.median(s))
    mad = float(np.median(np.abs(s - med))) / 0.6745
    if mad < 1e-9:
        return s, 0

    z = (s - med) / mad
    extreme = np.abs(z) > threshold
    damped = 0
    for i in range(len(s)):
        if not extreme[i]:
            continue
        neighbour_extreme = (i > 0 and extreme[i - 1]) or (i < len(s) - 1 and extreme[i + 1])
        if neighbour_extreme:
            continue  # part of a sustained shift - keep it
        s[i] = med + np.sign(z[i]) * threshold * mad
        damped += 1
    return s, damped


def fit_and_project(deseasonalised: np.ndarray, horizon: int) -> tuple[np.ndarray, float, str]:
    """Damped-trend exponential smoothing, with a safe fallback."""
    series = np.asarray(deseasonalised, dtype=float)

    if len(series) >= 6:
        try:
            model = ExponentialSmoothing(
                series,
                trend="add",
                damped_trend=True,
                seasonal=None,
                initialization_method="estimated",
            ).fit(optimized=True)
            point = np.asarray(model.forecast(horizon), dtype=float)
            resid = series - np.asarray(model.fittedvalues, dtype=float)
            sigma = float(np.std(resid, ddof=1)) if len(resid) > 1 else float(np.std(series))
            if np.all(np.isfinite(point)) and np.all(point > 0):
                return point, sigma, "Damped-trend exponential smoothing (statsmodels)"
        except Exception:
            pass

    # Fallback: trailing level plus a conservative linear drift.
    window = series[-6:]
    level = float(np.mean(window))
    drift = float(np.polyfit(np.arange(len(window)), window, 1)[0]) if len(window) > 2 else 0.0
    point = np.array([level + drift * (h + 1) for h in range(horizon)], dtype=float)
    sigma = float(np.std(window, ddof=1)) if len(window) > 1 else level * 0.05
    return point, sigma, "Trailing mean with linear drift (fallback)"


def forecast_series(frame: pd.DataFrame, label: str, horizon: int = HORIZON) -> dict[str, Any]:
    """Forecast one aggregated revenue series and compare it to budget."""
    monthly = (
        frame.groupby("period", sort=True)[["actual_revenue", "expected_revenue"]]
        .sum()
        .sort_index()
    )
    periods = pd.PeriodIndex(monthly.index, freq="M")

    index, base_level, growth = seasonal_profile(monthly["expected_revenue"], periods)
    season = np.array([index[p.month] for p in periods], dtype=float)

    deseasonalised = monthly["actual_revenue"].to_numpy(dtype=float) / np.maximum(season, 1e-9)
    fit_input, damped_months = damp_isolated_outliers(deseasonalised)
    point, sigma, model_name = fit_and_project(fit_input, horizon)

    future_periods = pd.period_range(periods[-1] + 1, periods=horizon, freq="M")
    n = len(periods)

    rows: list[dict[str, Any]] = []
    for h, fp in enumerate(future_periods):
        idx = index[fp.month]
        forecast = float(point[h] * idx)

        # Interval widens with the horizon, with a floor so it never looks
        # falsely precise on a short history.
        spread = Z_95 * sigma * np.sqrt(h + 1) * idx
        spread = max(spread, forecast * MIN_INTERVAL_PCT)

        budget = float(base_level * (1.0 + growth) ** (n + h) * idx)
        variance = forecast - budget

        rows.append({
            "period": str(fp),
            "label": _period_label(fp),
            "forecast": round(forecast, 2),
            "lower": round(max(0.0, forecast - spread), 2),
            "upper": round(forecast + spread, 2),
            "budget": round(budget, 2),
            "variance": round(variance, 2),
            "variance_pct": round(variance / budget * 100.0, 2) if budget else 0.0,
        })

    history = [
        {
            "period": str(p),
            "label": _period_label(p),
            "actual": round(float(monthly["actual_revenue"].iloc[i]), 2),
            "budget": round(float(monthly["expected_revenue"].iloc[i]), 2),
        }
        for i, p in enumerate(periods)
    ]

    forecast_total = float(sum(r["forecast"] for r in rows))
    budget_total = float(sum(r["budget"] for r in rows))
    lower_total = float(sum(r["lower"] for r in rows))
    upper_total = float(sum(r["upper"] for r in rows))
    variance_total = forecast_total - budget_total

    # A single array the dashboard can hand straight to Recharts: history and
    # forecast share an x-axis, and the last actual is repeated as the first
    # forecast point so the two lines join up instead of leaving a gap.
    series: list[dict[str, Any]] = []
    for i, h in enumerate(history):
        point_row = {
            "label": h["label"],
            "period": h["period"],
            "actual": h["actual"],
            "budget": h["budget"],
            "forecast": None,
            "lower": None,
            "upper": None,
            "range": None,
        }
        if i == len(history) - 1:
            point_row.update({
                "forecast": h["actual"],
                "lower": h["actual"],
                "upper": h["actual"],
                "range": [h["actual"], h["actual"]],
            })
        series.append(point_row)

    for r in rows:
        series.append({
            "label": r["label"],
            "period": r["period"],
            "actual": None,
            "budget": r["budget"],
            "forecast": r["forecast"],
            "lower": r["lower"],
            "upper": r["upper"],
            "range": [r["lower"], r["upper"]],
        })

    return {
        "revenue_stream": label,
        "model": model_name,
        "horizon_months": horizon,
        "history": history,
        "forecast": rows,
        "series": series,
        "forecast_total": round(forecast_total, 2),
        "forecast_lower_total": round(lower_total, 2),
        "forecast_upper_total": round(upper_total, 2),
        "budget_total": round(budget_total, 2),
        "variance_total": round(variance_total, 2),
        "variance_pct": round(variance_total / budget_total * 100.0, 2) if budget_total else 0.0,
        "monthly_growth_pct": round(growth * 100.0, 2),
        "outliers_damped": damped_months,
        "confidence_note": (
            f"95% range, widening with the forecast horizon. "
            f"Based on {n} months of collections."
            + (f" {damped_months} one-off month(s) damped so a single spike does "
               f"not set the trend." if damped_months else "")
        ),
    }


def build_forecast(df: pd.DataFrame | None = None, horizon: int = HORIZON) -> dict[str, Any]:
    """District-wide plus per-stream forecasts for the next `horizon` months."""
    if df is None:
        df = load_data()

    district = forecast_series(df, "All Revenue Streams", horizon)
    streams = [
        forecast_series(df[df["revenue_stream"] == s], s, horizon)
        for s in sorted(df["revenue_stream"].unique())
    ]

    future = [r["period"] for r in district["forecast"]]
    return {
        "horizon_months": horizon,
        "forecast_periods": future,
        "forecast_window": (
            f"{pd.Period(future[0], freq='M').strftime('%b %Y')} - "
            f"{pd.Period(future[-1], freq='M').strftime('%b %Y')}"
        ),
        "district": district,
        "streams": streams,
    }


def main() -> None:
    result = build_forecast()
    d = result["district"]

    print("=" * 78)
    print(f"FISCAL SENTINEL - collection forecast, {result['forecast_window']}")
    print("=" * 78)
    print(f"Model: {d['model']}")
    print(f"{d['confidence_note']}\n")

    print(f"{'Stream':<24}{'Forecast':>13}{'Range':>26}{'Budget':>13}{'Var':>9}")
    print("-" * 85)
    for s in result["streams"] + [d]:
        rng = f"{money(s['forecast_lower_total'])} - {money(s['forecast_upper_total'])}"
        print(f"{s['revenue_stream']:<24}{money(s['forecast_total']):>13}{rng:>26}"
              f"{money(s['budget_total']):>13}{s['variance_pct']:>8.1f}%")

    print("\nDistrict month by month:")
    print(f"  {'Month':<10}{'Forecast':>13}{'Low':>13}{'High':>13}{'Budget':>13}{'Var':>9}")
    for r in d["forecast"]:
        print(f"  {r['label']:<10}{money(r['forecast']):>13}{money(r['lower']):>13}"
              f"{money(r['upper']):>13}{money(r['budget']):>13}{r['variance_pct']:>8.1f}%")

    print("\n--- validation -------------------------------------------------------")
    checks = [
        ("Forecast horizon is 3 months", len(d["forecast"]) == 3, str(len(d["forecast"]))),
        ("Every stream forecast", len(result["streams"]) == 4, str(len(result["streams"]))),
        ("All point forecasts positive",
         all(r["forecast"] > 0 for s in result["streams"] for r in s["forecast"]), ""),
        ("Confidence range brackets the point forecast",
         all(r["lower"] <= r["forecast"] <= r["upper"]
             for s in result["streams"] + [d] for r in s["forecast"]), ""),
        ("Range widens with horizon",
         all(s["forecast"][2]["upper"] - s["forecast"][2]["lower"]
             >= s["forecast"][0]["upper"] - s["forecast"][0]["lower"]
             for s in result["streams"] + [d]), ""),
        ("Stream forecasts sum near the district total",
         abs(sum(s["forecast_total"] for s in result["streams"]) - d["forecast_total"])
         / d["forecast_total"] < 0.12,
         f"{sum(s['forecast_total'] for s in result['streams']):,.0f} vs {d['forecast_total']:,.0f}"),
        ("Chart series joins history to forecast",
         d["series"][17]["forecast"] is not None and d["series"][17]["actual"] is not None, ""),
    ]
    failed = 0
    for name, ok, note in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")


if __name__ == "__main__":
    main()
