"""
Fiscal Sentinel - Financial Risk Scoring engine.

Scores every ward / revenue-stream "book" from 0-100 and explains why.

    Financial Risk Score = 40%  revenue deviation
                         + 25%  historical abnormality
                         + 20%  transaction pattern anomaly
                         + 15%  peer-ward deviation

Bands:  0-29 Normal | 30-59 Watch | 60-79 High | 80-100 Critical

Every component is computed against `expected_revenue`, which already carries
the seasonal profile of each stream. A market that always empties out in
January therefore has a near-zero deviation in January and cannot be scored as
a risk. `seasonally_explained` records that judgement explicitly so the brief
can say so in words.

Detected events are described as financial anomalies or potential revenue
leakage. Nothing here concludes intent.

Run:
    python backend/analytics.py
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

DATA_CSV = Path(__file__).resolve().parents[1] / "data" / "rdc_financial_data.csv"

# Component weights - these define the Financial Risk Score.
WEIGHTS = {
    "revenue_deviation": 0.40,
    "historical_abnormality": 0.25,
    "transaction_pattern": 0.20,
    "peer_deviation": 0.15,
}

RECENT_WINDOW = 3          # months treated as "now"
RECENCY_WEIGHTS = [0.50, 0.30, 0.20]   # most recent month first
BASELINE_MIN_MONTHS = 6    # months of history needed before z-scoring

# Tolerances. Collection is noisy; small misses are not findings.
DEVIATION_DEADBAND = 6.0   # +/- % of expected treated as normal noise
SHORTFALL_FULL_SCALE = 40.0   # % shortfall (beyond deadband) that scores 100
OVERSHOOT_FULL_SCALE = 65.0   # % overshoot (beyond deadband) that scores 100
SEASONAL_EXPLAINED_BAND = 10.0  # |deviation| under this = the dip is seasonal

BANDS = [
    (80.0, "Critical"),
    (60.0, "High"),
    (30.0, "Watch"),
    (0.0, "Normal"),
]


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------

def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(min(hi, max(lo, x)))


def robust_center_scale(values: np.ndarray) -> tuple[float, float]:
    """Median and a MAD-based sigma, with graceful fallbacks for flat data."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return 0.0, 1.0
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    sigma = mad / 0.6745
    if sigma < 1e-6:
        sigma = float(np.std(values))
    if sigma < 1e-6:
        sigma = 1.0
    return med, sigma


def robust_z(x: float, values: np.ndarray) -> float:
    med, sigma = robust_center_scale(values)
    return float((x - med) / sigma)


def scale_score(magnitude: float, full_scale: float, deadband: float = 0.0) -> float:
    """Map a magnitude onto 0-100, ignoring anything inside the deadband."""
    effective = max(0.0, abs(magnitude) - deadband)
    if full_scale <= 0:
        return 0.0
    return clamp(effective / full_scale * 100.0)


def weighted_recent(values: list[float]) -> float:
    """Recency-weighted mean of a window given most-recent-first."""
    if not values:
        return 0.0
    w = RECENCY_WEIGHTS[: len(values)]
    w = [x / sum(w) for x in w]
    return float(sum(v * wi for v, wi in zip(values, w)))


def band_for(score: float) -> str:
    for threshold, name in BANDS:
        if score >= threshold:
            return name
    return "Normal"


def slugify(*parts: str) -> str:
    raw = "-".join(parts).lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")


def money(x: float) -> str:
    return f"${x:,.0f}"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(csv_path: Path | str = DATA_CSV) -> pd.DataFrame:
    """Load the council dataset and derive the per-book working columns."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. Run `python backend/generate_data.py` first."
        )

    df = pd.read_csv(csv_path, parse_dates=["date"])
    df["period"] = df["date"].dt.to_period("M").astype(str)
    df["book"] = df["ward"] + " / " + df["revenue_stream"]
    df = df.sort_values(["ward", "revenue_stream", "date"], ignore_index=True)

    # Receipt volume is strongly seasonal (a market is busier in December), so
    # it is deseasonalised before any month is compared to the book's history.
    # Otherwise every high season reads as a volume surge.
    df["month_num"] = df["date"].dt.month
    book_mean_txn = df.groupby(["ward", "revenue_stream"], sort=False)["transactions"].transform("mean")
    df["_txn_ratio"] = df["transactions"] / book_mean_txn
    season_index = df.groupby(["revenue_stream", "month_num"], sort=False)["_txn_ratio"].transform("median")
    df["transactions_adj"] = df["transactions"] / season_index.replace(0.0, np.nan)

    grp = df.groupby(["ward", "revenue_stream"], sort=False)

    # Expanding medians give each book a "what is normal for me" reference that
    # only ever looks backwards, so a new anomaly cannot quietly redefine normal.
    def trailing_median(col: str) -> pd.Series:
        return grp[col].transform(lambda s: s.shift(1).expanding(min_periods=3).median())

    df["avg_txn_baseline"] = trailing_median("average_transaction")
    df["txn_baseline"] = trailing_median("transactions_adj")

    df["avg_txn_shift_pct"] = (
        (df["average_transaction"] - df["avg_txn_baseline"]) / df["avg_txn_baseline"] * 100.0
    )
    df["txn_shift_pct"] = (
        (df["transactions_adj"] - df["txn_baseline"]) / df["txn_baseline"] * 100.0
    )
    # Revenue falling while receipts keep coming is the signature of collected
    # money not being banked. This column measures exactly that divergence.
    df["revenue_txn_divergence"] = df["deviation_pct"] - df["txn_shift_pct"]
    df["gap_ratio"] = df["revenue_gap"] / df["expected_revenue"] * 100.0

    # Round-number banking rate, measured per collector over their whole book.
    round_rate = df.groupby("collector_id")["is_round_number"].transform("mean") * 100.0
    df["collector_round_rate"] = round_rate

    for col in ["avg_txn_shift_pct", "txn_shift_pct", "revenue_txn_divergence"]:
        df[col] = df[col].fillna(0.0)

    return df


# ---------------------------------------------------------------------------
# Isolation Forest
# ---------------------------------------------------------------------------

ISO_FEATURES = [
    "deviation_pct",
    "avg_txn_shift_pct",
    "txn_shift_pct",
    "revenue_txn_divergence",
    "collector_round_rate",
]


def add_isolation_scores(df: pd.DataFrame, seed: int = 7) -> pd.DataFrame:
    """Unsupervised outlier score per record, normalised to 0-100."""
    x = df[ISO_FEATURES].to_numpy(dtype=float)
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    model = IsolationForest(
        n_estimators=400,
        contamination=0.06,
        max_samples="auto",
        random_state=seed,
    )
    model.fit(x)

    # decision_function: lower = more isolated. Flip, then rank-normalise so the
    # score is a stable 0-100 regardless of the raw score distribution.
    raw = -model.decision_function(x)
    ranks = pd.Series(raw).rank(pct=True).to_numpy()
    df = df.copy()
    df["iso_raw"] = raw
    df["iso_score"] = np.round(ranks * 100.0, 2)
    df["iso_flag"] = model.predict(x) == -1
    return df


# ---------------------------------------------------------------------------
# Per-book scoring
# ---------------------------------------------------------------------------

def _peer_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Deviation of each ward against its peers on the same stream and month."""
    out = df[["period", "ward", "revenue_stream", "deviation_pct"]].copy()
    grp = out.groupby(["revenue_stream", "period"], sort=False)["deviation_pct"]

    def z(series: pd.Series) -> pd.Series:
        med, sigma = robust_center_scale(series.to_numpy())
        return (series - med) / sigma

    out["peer_z"] = grp.transform(z)
    return out


def score_book(book: pd.DataFrame, peers: pd.DataFrame) -> dict[str, Any]:
    """Score one ward/stream book and assemble its explanation."""
    book = book.sort_values("date", ignore_index=True)
    ward = book["ward"].iloc[0]
    stream = book["revenue_stream"].iloc[0]
    collector = book["collector_id"].iloc[-1]

    recent = book.tail(RECENT_WINDOW).iloc[::-1]          # most recent first
    baseline = book.iloc[: max(0, len(book) - RECENT_WINDOW)]
    latest = book.iloc[-1]

    # -- 1. Revenue deviation (40%) -------------------------------------
    dev_window = recent["deviation_pct"].tolist()
    dev_weighted = weighted_recent(dev_window)

    def deviation_points(d: float) -> float:
        scale = SHORTFALL_FULL_SCALE if d < 0 else OVERSHOOT_FULL_SCALE
        return scale_score(d, scale, DEVIATION_DEADBAND)

    sustained = deviation_points(dev_weighted)
    # A sharp one-off event a month or two back still needs attention, so the
    # worst single month in the window carries through at a discount.
    worst_idx = int(np.argmax([abs(d) for d in dev_window])) if dev_window else 0
    worst_single = deviation_points(dev_window[worst_idx]) * 0.75 if dev_window else 0.0
    c_deviation = clamp(max(sustained, worst_single))

    # -- 2. Historical abnormality (25%) --------------------------------
    if len(baseline) >= BASELINE_MIN_MONTHS:
        hist = baseline["deviation_pct"].to_numpy()
        z_scores = [abs(robust_z(d, hist)) for d in dev_window]
        stat_component = max(
            scale_score(weighted_recent(z_scores), 3.5),
            scale_score(max(z_scores), 3.5) * 0.8,
        )
    else:
        stat_component = 0.0
    iso_component = float(recent["iso_score"].max()) if len(recent) else 0.0
    c_history = clamp(0.60 * stat_component + 0.40 * iso_component)

    # -- 3. Transaction pattern anomaly (20%) ---------------------------
    avg_shift = weighted_recent(recent["avg_txn_shift_pct"].tolist())
    divergence = weighted_recent(recent["revenue_txn_divergence"].tolist())
    round_rate = float(book["is_round_number"].mean() * 100.0)

    avg_shift_pts = scale_score(avg_shift, 35.0, 8.0)
    divergence_pts = scale_score(divergence, 40.0, 10.0)
    round_pts = scale_score(round_rate, 45.0)  # 45%+ round months scores 100

    pattern_blend = 0.45 * avg_shift_pts + 0.25 * divergence_pts + 0.30 * round_pts
    c_pattern = clamp(max(pattern_blend, round_pts, avg_shift_pts * 0.9))

    # -- 4. Peer-ward deviation (15%) -----------------------------------
    peer_rows = peers[
        (peers["ward"] == ward)
        & (peers["revenue_stream"] == stream)
        & (peers["period"].isin(recent["period"]))
    ].set_index("period")
    peer_z = [abs(float(peer_rows.loc[p, "peer_z"])) if p in peer_rows.index else 0.0
              for p in recent["period"]]
    c_peer = clamp(max(scale_score(weighted_recent(peer_z), 3.0),
                       scale_score(max(peer_z) if peer_z else 0.0, 3.0) * 0.75))

    components = {
        "revenue_deviation": round(c_deviation, 1),
        "historical_abnormality": round(c_history, 1),
        "transaction_pattern": round(c_pattern, 1),
        "peer_deviation": round(c_peer, 1),
    }
    risk_score = round(sum(components[k] * WEIGHTS[k] for k in WEIGHTS), 1)

    # -- Seasonality judgement ------------------------------------------
    own_average = float(book["actual_revenue"].mean())
    recent_average = float(recent["actual_revenue"].mean())
    raw_change = (recent_average - own_average) / own_average * 100.0 if own_average else 0.0
    seasonally_explained = bool(raw_change < -12.0 and abs(dev_weighted) <= SEASONAL_EXPLAINED_BAND)

    window_gap = float(recent["revenue_gap"].sum())
    annualised_exposure = float(recent["revenue_gap"].mean()) * 12.0

    result = {
        "id": slugify(ward, stream),
        "ward": ward,
        "revenue_stream": stream,
        "collector_id": collector,
        "risk_score": risk_score,
        "risk_band": band_for(risk_score),
        "components": components,
        "component_weights": {k: round(v * 100) for k, v in WEIGHTS.items()},
        "contributions": {k: round(components[k] * WEIGHTS[k], 1) for k in WEIGHTS},
        "period": str(latest["period"]),
        "actual_revenue": float(latest["actual_revenue"]),
        "expected_revenue": float(latest["expected_revenue"]),
        "revenue_gap": float(latest["revenue_gap"]),
        "deviation_pct": float(latest["deviation_pct"]),
        "window_deviation_pct": round(dev_weighted, 1),
        "window_gap": round(window_gap, 2),
        "annualised_exposure": round(annualised_exposure, 2),
        "transactions": int(latest["transactions"]),
        "average_transaction": float(latest["average_transaction"]),
        "avg_transaction_shift_pct": round(avg_shift, 1),
        "transaction_shift_pct": round(weighted_recent(recent["txn_shift_pct"].tolist()), 1),
        "round_number_rate": round(round_rate, 1),
        "iso_flagged": bool(recent["iso_flag"].any()),
        "seasonally_explained": seasonally_explained,
        "months_observed": int(len(book)),
    }
    result["drivers"] = build_drivers(result)
    result["headline"] = build_headline(result)
    return result


def build_drivers(r: dict[str, Any]) -> list[dict[str, str]]:
    """Plain-language reasons behind the score, strongest first."""
    drivers: list[dict[str, str]] = []
    dev = r["window_deviation_pct"]

    if r["seasonally_explained"]:
        drivers.append({
            "label": "Seasonal pattern",
            "detail": (f"Collections are down on the annual average, but are within "
                       f"{abs(dev):.1f}% of the seasonally adjusted expectation. "
                       f"This is the normal cycle for {r['revenue_stream']}, not a shortfall."),
            "severity": "info",
        })

    if dev <= -DEVIATION_DEADBAND:
        drivers.append({
            "label": "Sustained revenue shortfall",
            "detail": (f"Collections are running {abs(dev):.1f}% below the seasonally "
                       f"adjusted expectation, a gap of {money(abs(r['window_gap']))} "
                       f"over the last {RECENT_WINDOW} months."),
            "severity": "high" if dev <= -25 else "medium",
        })
    elif dev >= DEVIATION_DEADBAND:
        drivers.append({
            "label": "Collections above expectation",
            "detail": (f"Collections are running {dev:.1f}% above the seasonally adjusted "
                       f"expectation, {money(abs(r['window_gap']))} over the last "
                       f"{RECENT_WINDOW} months. Worth confirming the basis of assessment."),
            "severity": "medium",
        })

    shift = r["avg_transaction_shift_pct"]
    if abs(shift) >= 12:
        direction = "fallen" if shift < 0 else "risen"
        drivers.append({
            "label": "Average receipt value moved",
            "detail": (f"The average receipt has {direction} {abs(shift):.1f}% against this "
                       f"book's own history while receipt volume moved "
                       f"{r['transaction_shift_pct']:+.1f}%. Revenue and activity are "
                       f"no longer moving together."),
            "severity": "high" if abs(shift) >= 30 else "medium",
        })

    if r["round_number_rate"] >= 25:
        drivers.append({
            "label": "Round-number concentration",
            "detail": (f"{r['round_number_rate']:.0f}% of months banked by collector "
                       f"{r['collector_id']} land on an exact round figure. Genuine "
                       f"receipt totals rarely do. This is a records and control "
                       f"concern rather than a revenue shortfall."),
            "severity": "high",
        })

    if r["components"]["peer_deviation"] >= 50:
        drivers.append({
            "label": "Out of line with peer wards",
            "detail": (f"Other wards collecting {r['revenue_stream']} in the same months "
                       f"are not showing this movement, so a district-wide cause is "
                       f"unlikely."),
            "severity": "medium",
        })

    if r["iso_flagged"] and len(drivers) < 2:
        drivers.append({
            "label": "Statistical outlier",
            "detail": ("The Isolation Forest model separates recent months for this book "
                       "from the district's normal collection pattern."),
            "severity": "medium",
        })

    if not drivers:
        drivers.append({
            "label": "Within expected range",
            "detail": ("Collections, receipt volumes and average receipt values are all "
                       "tracking the seasonally adjusted expectation."),
            "severity": "info",
        })
    return drivers


def build_headline(r: dict[str, Any]) -> str:
    dev = r["window_deviation_pct"]
    if r["risk_band"] == "Normal":
        return f"{r['ward']} {r['revenue_stream']} is collecting in line with expectation."
    if r["round_number_rate"] >= 25 and abs(dev) < 15:
        return (f"{r['ward']} {r['revenue_stream']} shows a banking-records pattern that "
                f"needs verification.")
    if dev <= -DEVIATION_DEADBAND:
        return (f"{r['ward']} {r['revenue_stream']} is {abs(dev):.0f}% below expectation - "
                f"potential revenue leakage of {money(abs(r['window_gap']))}.")
    if dev >= DEVIATION_DEADBAND:
        return (f"{r['ward']} {r['revenue_stream']} is {dev:.0f}% above expectation and the "
                f"increase is not explained by receipt volume.")
    return f"{r['ward']} {r['revenue_stream']} shows an irregular collection pattern."


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RiskEngine:
    """Loads the data once, scores every book, and answers the API's questions."""

    def __init__(self, csv_path: Path | str = DATA_CSV):
        self.df = add_isolation_scores(load_data(csv_path))
        self.peers = _peer_frame(self.df)
        self.latest_period = str(self.df["period"].max())
        self.books = self._score_all()
        self.by_id = {b["id"]: b for b in self.books}

    def _score_all(self) -> list[dict[str, Any]]:
        results = []
        for (_ward, _stream), book in self.df.groupby(["ward", "revenue_stream"], sort=False):
            results.append(score_book(book, self.peers))
        results.sort(key=lambda r: r["risk_score"], reverse=True)
        return results

    # -- queries --------------------------------------------------------
    def anomalies(self, min_score: float = 30.0) -> list[dict[str, Any]]:
        """Books that need attention, highest risk first."""
        return [b for b in self.books if b["risk_score"] >= min_score]

    def radar(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Every book, highest risk first - the Financial Risk Radar."""
        return self.books[:limit] if limit else list(self.books)

    def detail(self, book_id: str) -> dict[str, Any] | None:
        book = self.by_id.get(book_id)
        if book is None:
            return None
        rows = self.df[
            (self.df["ward"] == book["ward"])
            & (self.df["revenue_stream"] == book["revenue_stream"])
        ].sort_values("date")

        trend = [
            {
                "period": str(r["period"]),
                "label": pd.Period(r["period"], freq="M").strftime("%b %y"),
                "expected": float(r["expected_revenue"]),
                "actual": float(r["actual_revenue"]),
                "gap": float(r["revenue_gap"]),
                "deviation_pct": float(r["deviation_pct"]),
                "transactions": int(r["transactions"]),
                "average_transaction": float(r["average_transaction"]),
                "is_round_number": bool(r["is_round_number"]),
                "flagged": bool(r["iso_flag"]),
            }
            for _, r in rows.iterrows()
        ]

        detail = dict(book)
        detail["trend"] = trend
        detail["peer_comparison"] = self._peer_comparison(book)
        detail["first_flagged_period"] = next(
            (p["period"] for p in trend if p["flagged"]), None
        )
        return detail

    def _peer_comparison(self, book: dict[str, Any]) -> list[dict[str, Any]]:
        """How every ward is doing on this stream over the recent window."""
        recent_periods = sorted(self.df["period"].unique())[-RECENT_WINDOW:]
        sl = self.df[
            (self.df["revenue_stream"] == book["revenue_stream"])
            & (self.df["period"].isin(recent_periods))
        ]
        agg = sl.groupby("ward", sort=True).agg(
            actual=("actual_revenue", "sum"),
            expected=("expected_revenue", "sum"),
        )
        agg["deviation_pct"] = (agg["actual"] - agg["expected"]) / agg["expected"] * 100.0
        return [
            {
                "ward": ward,
                "deviation_pct": round(float(row["deviation_pct"]), 1),
                "actual": float(row["actual"]),
                "expected": float(row["expected"]),
                "is_subject": ward == book["ward"],
            }
            for ward, row in agg.iterrows()
        ]

    def kpi_summary(self) -> dict[str, Any]:
        latest = self.df[self.df["period"] == self.latest_period]
        prev_periods = sorted(self.df["period"].unique())
        prev_period = prev_periods[-2] if len(prev_periods) > 1 else self.latest_period
        prev = self.df[self.df["period"] == prev_period]

        actual = float(latest["actual_revenue"].sum())
        expected = float(latest["expected_revenue"].sum())
        prev_actual = float(prev["actual_revenue"].sum())

        anomalies = self.anomalies()
        bands = {name: 0 for _, name in BANDS}
        for b in self.books:
            bands[b["risk_band"]] += 1

        exposure = sum(abs(b["window_gap"]) for b in anomalies if b["window_gap"] < 0)

        return {
            "period": self.latest_period,
            "period_label": pd.Period(self.latest_period, freq="M").strftime("%B %Y"),
            "revenue_this_month": round(actual, 2),
            "expected_this_month": round(expected, 2),
            "revenue_gap": round(actual - expected, 2),
            "deviation_pct": round((actual - expected) / expected * 100.0, 2),
            "month_on_month_pct": round((actual - prev_actual) / prev_actual * 100.0, 2),
            "anomaly_count": len(anomalies),
            "critical_count": bands["Critical"],
            "high_count": bands["High"],
            "watch_count": bands["Watch"],
            "books_monitored": len(self.books),
            "exposure_identified": round(exposure, 2),
            "band_counts": bands,
        }


_ENGINE: RiskEngine | None = None


def get_engine(refresh: bool = False) -> RiskEngine:
    """Process-wide singleton so the API scores the district once, not per request."""
    global _ENGINE
    if _ENGINE is None or refresh:
        _ENGINE = RiskEngine()
    return _ENGINE


# ---------------------------------------------------------------------------
# CLI self-check
# ---------------------------------------------------------------------------

def main() -> None:
    engine = get_engine()
    k = engine.kpi_summary()

    print("=" * 78)
    print(f"FISCAL SENTINEL - risk scoring for {k['period_label']}")
    print("=" * 78)
    print(f"Collected {money(k['revenue_this_month'])} against an expected "
          f"{money(k['expected_this_month'])}  ({k['deviation_pct']:+.1f}%)")
    print(f"{k['books_monitored']} books monitored, {k['anomaly_count']} need attention "
          f"(Critical {k['critical_count']} / High {k['high_count']} / Watch {k['watch_count']})")
    print(f"Exposure identified: {money(k['exposure_identified'])}\n")

    print(f"{'Ward / Stream':<34}{'Score':>7} {'Band':<10}"
          f"{'Dev':>6}{'Hist':>6}{'Txn':>6}{'Peer':>6}")
    print("-" * 78)
    for b in engine.radar(12):
        c = b["components"]
        print(f"{b['ward'] + ' / ' + b['revenue_stream']:<34}"
              f"{b['risk_score']:>7.1f} {b['risk_band']:<10}"
              f"{c['revenue_deviation']:>6.0f}{c['historical_abnormality']:>6.0f}"
              f"{c['transaction_pattern']:>6.0f}{c['peer_deviation']:>6.0f}")

    print("\n--- top findings -----------------------------------------------------")
    for b in engine.anomalies()[:4]:
        print(f"\n[{b['risk_band'].upper()} {b['risk_score']:.0f}] {b['headline']}")
        for d in b["drivers"]:
            print(f"    - {d['label']}: {d['detail']}")

    # ---- assertions the demo depends on --------------------------------
    print("\n--- validation -------------------------------------------------------")
    checks: list[tuple[str, bool, str]] = []

    leak = engine.by_id.get(slugify("Ward 4", "Market Fees"))
    checks.append(("Ward 4 Market Fees leakage detected",
                   leak is not None and leak["risk_band"] in ("High", "Critical"),
                   f"score {leak['risk_score'] if leak else 'n/a'}"))

    spike = engine.by_id.get(slugify("Ward 7", "Business Licenses"))
    checks.append(("Ward 7 Business Licenses spike detected",
                   spike is not None and spike["risk_score"] >= 30,
                   f"score {spike['risk_score'] if spike else 'n/a'}"))

    rnd = engine.by_id.get(slugify("Ward 6", "Beer Hall Levies"))
    checks.append(("Ward 6 round-number pattern detected",
                   rnd is not None and rnd["risk_score"] >= 30,
                   f"score {rnd['risk_score'] if rnd else 'n/a'}, "
                   f"{rnd['round_number_rate'] if rnd else 0:.0f}% round months"))

    # Seasonality: score every book as if a deep-seasonal month were "now" and
    # confirm none of the clean books get flagged for it.
    seasonal_ok = True
    worst = ("", 0.0)
    for stream, cutoff in [("Business Licenses", "2025-11"), ("Market Fees", "2025-03"),
                           ("Beer Hall Levies", "2025-05")]:
        sub = engine.df[(engine.df["revenue_stream"] == stream)
                        & (engine.df["period"] <= cutoff)]
        for (_w, _s), book in sub.groupby(["ward", "revenue_stream"], sort=False):
            scored = score_book(book, engine.peers)
            if scored["risk_score"] > worst[1]:
                worst = (f"{scored['ward']} / {stream} @ {cutoff}", scored["risk_score"])
            if scored["risk_score"] >= 60:
                seasonal_ok = False
    checks.append(("Seasonal troughs are not flagged as anomalies", seasonal_ok,
                   f"worst seasonal-month score {worst[1]:.1f} ({worst[0]})"))

    normals = [b for b in engine.books if b["risk_band"] == "Normal"]
    checks.append(("Most books stay Normal (no alert fatigue)",
                   len(normals) >= len(engine.books) * 0.5,
                   f"{len(normals)}/{len(engine.books)} normal"))

    failed = 0
    for name, ok, note in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  ({note})")
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")


if __name__ == "__main__":
    main()
