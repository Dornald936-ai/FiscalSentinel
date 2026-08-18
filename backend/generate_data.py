"""
Fiscal Sentinel - synthetic Rural District Council (RDC) revenue dataset.

Generates 18 months of monthly revenue records across 8 wards and 4 revenue
streams, with realistic seasonality, ward size differences, collector
assignments and per-month noise.

Three scenarios are deliberately injected so the analytics layer has something
real to find:

  (a) LEAKAGE      Ward 4 / Market Fees collapses ~47% from March 2026 onwards
                   while transaction volume stays flat - the classic signature
                   of revenue never reaching the council account.
  (b) SPIKE        Ward 7 / Business Licenses spikes in April 2026 far beyond
                   what the licence renewal cycle explains.
  (c) ROUND NUMBER Collector COL-024 (Ward 6 / Beer Hall Levies) banks
                   suspiciously round amounts in most months - a control
                   weakness rather than a shortfall.

Seasonality is baked into `expected_revenue`, so a genuine seasonal dip shows a
near-zero deviation and must never register as an anomaly downstream.

Run:
    python backend/generate_data.py
Writes:
    data/rdc_financial_data.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

SEED = 424242
START_PERIOD = "2025-01"
N_MONTHS = 18  # Jan 2025 -> Jun 2026

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OUTPUT_CSV = DATA_DIR / "rdc_financial_data.csv"

WARDS = [f"Ward {i}" for i in range(1, 9)]

REVENUE_STREAMS = [
    "Property Rates",
    "Market Fees",
    "Business Licenses",
    "Beer Hall Levies",
]

# Council-wide monthly baseline per stream, in USD, before ward scaling.
STREAM_BASELINE = {
    "Property Rates": 42_000.0,
    "Market Fees": 18_000.0,
    "Business Licenses": 12_500.0,
    "Beer Hall Levies": 9_400.0,
}

# Typical value of a single receipt for each stream, in USD.
STREAM_TICKET = {
    "Property Rates": 86.0,
    "Market Fees": 11.5,
    "Business Licenses": 155.0,
    "Beer Hall Levies": 44.0,
}

# Relative size / collection capacity of each ward.
WARD_SCALE = {
    "Ward 1": 1.45,  # council seat, dense business district
    "Ward 2": 1.10,
    "Ward 3": 0.85,
    "Ward 4": 1.20,  # large growth point with the district's biggest market
    "Ward 5": 0.70,
    "Ward 6": 0.95,
    "Ward 7": 1.05,
    "Ward 8": 0.60,  # remote, sparsely settled
}

# Multiplicative seasonal factors by calendar month (index 0 == January).
# These are strong on purpose: the analytics layer has to prove it can ignore
# them. Each vector averages to ~1.0 across the year.
SEASONAL_FACTORS = {
    # Rates run on a billing cycle: heavy Jan-Mar demand notices, mid-year
    # supplementary billing, quiet festive season.
    "Property Rates": [1.28, 1.20, 1.14, 0.98, 0.92, 0.95, 1.10, 1.02, 0.94, 0.90, 0.83, 0.74],
    # Markets die after the festive season, recover at harvest, peak in December.
    "Market Fees": [0.58, 0.64, 0.86, 1.18, 1.24, 1.12, 1.02, 0.96, 0.92, 1.00, 1.20, 1.48],
    # Licences renew annually in January, with a smaller mid-year catch-up.
    "Business Licenses": [2.35, 1.42, 1.02, 0.78, 0.66, 0.62, 0.94, 0.74, 0.58, 0.54, 0.62, 0.73],
    # Beer hall takings follow the agricultural cash cycle and peak in December.
    "Beer Hall Levies": [0.94, 0.72, 0.68, 1.02, 1.18, 1.22, 1.16, 1.10, 0.96, 0.88, 1.02, 1.62],
}

# Gentle underlying growth per month (inflation + widening revenue base).
STREAM_MONTHLY_GROWTH = {
    "Property Rates": 0.0055,
    "Market Fees": 0.0070,
    "Business Licenses": 0.0040,
    "Beer Hall Levies": 0.0060,
}

# Month-to-month collection noise (std-dev of the multiplicative shock).
STREAM_NOISE = {
    "Property Rates": 0.055,
    "Market Fees": 0.070,
    "Business Licenses": 0.080,
    "Beer Hall Levies": 0.065,
}

# Structural collection efficiency per ward: remote wards simply under-collect
# a little every month. This is a known, stable condition - not an anomaly.
WARD_EFFICIENCY = {
    "Ward 1": 1.02,
    "Ward 2": 0.99,
    "Ward 3": 0.96,
    "Ward 4": 1.01,
    "Ward 5": 0.94,
    "Ward 6": 0.98,
    "Ward 7": 1.00,
    "Ward 8": 0.92,
}

# --------------------------------------------------------------------------
# Injected scenarios
# --------------------------------------------------------------------------

# (a) Sustained revenue leakage.
LEAKAGE = {
    "ward": "Ward 4",
    "revenue_stream": "Market Fees",
    "from_period": "2026-03",
    "retention": 0.53,  # ~47% of the money stops arriving
}

# (b) Unexplained single-month surge.
SPIKE = {
    "ward": "Ward 7",
    "revenue_stream": "Business Licenses",
    "period": "2026-04",
    "multiplier": 2.85,
}

# (c) Round-number banking concentration.
ROUND_NUMBER = {
    "ward": "Ward 6",
    "revenue_stream": "Beer Hall Levies",
    "rounding_unit": 500.0,
    "share_of_months": 0.72,
    "drag": 0.92,  # mild under-collection, too small to trip a deviation alarm
}


def collector_id(ward: str, revenue_stream: str) -> str:
    """Stable collector assignment: one collector owns each ward/stream book."""
    w = WARDS.index(ward)
    s = REVENUE_STREAMS.index(revenue_stream)
    return f"COL-{w * len(REVENUE_STREAMS) + s + 1:03d}"


def build_dataset(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    periods = pd.period_range(start=START_PERIOD, periods=N_MONTHS, freq="M")

    leak_start = pd.Period(LEAKAGE["from_period"], freq="M")
    spike_period = pd.Period(SPIKE["period"], freq="M")

    # Decide up-front which months the round-number collector "tidies up".
    n_round = int(round(N_MONTHS * ROUND_NUMBER["share_of_months"]))
    round_months = set(
        pd.PeriodIndex(rng.choice(periods.astype(str), size=n_round, replace=False), freq="M")
    )

    rows: list[dict] = []

    for ward in WARDS:
        for stream in REVENUE_STREAMS:
            cid = collector_id(ward, stream)
            base = STREAM_BASELINE[stream] * WARD_SCALE[ward]
            ticket = STREAM_TICKET[stream] * rng.uniform(0.92, 1.08)
            seasonal = SEASONAL_FACTORS[stream]
            growth = STREAM_MONTHLY_GROWTH[stream]
            noise_sd = STREAM_NOISE[stream]

            is_leak_book = ward == LEAKAGE["ward"] and stream == LEAKAGE["revenue_stream"]
            is_spike_book = ward == SPIKE["ward"] and stream == SPIKE["revenue_stream"]
            is_round_book = ward == ROUND_NUMBER["ward"] and stream == ROUND_NUMBER["revenue_stream"]

            for t, period in enumerate(periods):
                month_idx = period.month - 1

                # ---- Budgeted / expected position -------------------------
                expected = base * seasonal[month_idx] * (1.0 + growth) ** t
                expected_transactions = expected / ticket

                # ---- What was actually collected --------------------------
                shock = rng.normal(1.0, noise_sd)
                actual = expected * WARD_EFFICIENCY[ward] * shock

                # Transaction count drifts on its own noise, so the average
                # receipt value moves independently of total revenue.
                transactions = expected_transactions * rng.normal(1.0, 0.045)

                scenario = ""

                # (a) Leakage: money stops arriving, traders keep trading.
                if is_leak_book and period >= leak_start:
                    actual *= LEAKAGE["retention"]
                    transactions *= rng.normal(0.99, 0.02)  # volume holds up
                    scenario = "leakage"

                # (b) Spike: revenue balloons, receipt count barely moves.
                if is_spike_book and period == spike_period:
                    actual *= SPIKE["multiplier"]
                    transactions *= 1.18
                    scenario = "spike"

                # (c) Round-number concentration on an otherwise dull book.
                if is_round_book:
                    actual *= ROUND_NUMBER["drag"]
                    if period in round_months:
                        unit = ROUND_NUMBER["rounding_unit"]
                        actual = max(unit, round(actual / unit) * unit)
                        scenario = "round_number"

                transactions = int(max(1, round(transactions)))
                actual = round(float(actual), 2)
                expected = round(float(expected), 2)

                # A monthly total that lands exactly on a 100 boundary is not
                # something an honest pile of receipts normally does.
                is_round = bool(actual > 0 and actual % 100 == 0)

                rows.append(
                    {
                        "date": period.to_timestamp().date().isoformat(),
                        "ward": ward,
                        "revenue_stream": stream,
                        "collector_id": cid,
                        "expected_revenue": expected,
                        "actual_revenue": actual,
                        "transactions": transactions,
                        "revenue_gap": round(actual - expected, 2),
                        "deviation_pct": round((actual - expected) / expected * 100.0, 2),
                        "is_round_number": is_round,
                        "average_transaction": round(actual / transactions, 2),
                        "_scenario": scenario,
                    }
                )

    df = pd.DataFrame(rows)
    df = df.sort_values(["date", "ward", "revenue_stream"], ignore_index=True)
    return df


COLUMNS = [
    "date",
    "ward",
    "revenue_stream",
    "collector_id",
    "expected_revenue",
    "actual_revenue",
    "transactions",
    "revenue_gap",
    "deviation_pct",
    "is_round_number",
    "average_transaction",
]


def main() -> None:
    df = build_dataset()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df[COLUMNS].to_csv(OUTPUT_CSV, index=False)

    print(f"Wrote {len(df):,} rows -> {OUTPUT_CSV}")
    print(f"Period: {df['date'].min()} .. {df['date'].max()}")
    print(f"Wards: {df['ward'].nunique()}   Streams: {df['revenue_stream'].nunique()}"
          f"   Collectors: {df['collector_id'].nunique()}")
    print(f"Total collected: ${df['actual_revenue'].sum():,.0f}"
          f"   against expected ${df['expected_revenue'].sum():,.0f}")

    print("\n--- injected scenario check -------------------------------------")

    leak = df[(df["ward"] == LEAKAGE["ward"])
              & (df["revenue_stream"] == LEAKAGE["revenue_stream"])
              & (df["date"] >= "2026-03-01")]
    print(f"(a) {LEAKAGE['ward']} / {LEAKAGE['revenue_stream']} from Mar 2026: "
          f"mean deviation {leak['deviation_pct'].mean():.1f}%")

    spike = df[(df["ward"] == SPIKE["ward"])
               & (df["revenue_stream"] == SPIKE["revenue_stream"])
               & (df["date"] == "2026-04-01")]
    print(f"(b) {SPIKE['ward']} / {SPIKE['revenue_stream']} Apr 2026: "
          f"deviation {spike['deviation_pct'].iloc[0]:+.1f}%")

    rnd = df[df["collector_id"] == collector_id(ROUND_NUMBER["ward"], ROUND_NUMBER["revenue_stream"])]
    others = df[df["collector_id"] != rnd["collector_id"].iloc[0]]
    print(f"(c) collector {rnd['collector_id'].iloc[0]}: "
          f"{rnd['is_round_number'].mean():.0%} round-number months "
          f"(all other collectors: {others['is_round_number'].mean():.1%})")

    print("\n--- seasonality sanity (must stay near 0% deviation) ------------")
    for stream, month in [("Market Fees", "2025-01"), ("Business Licenses", "2025-09"),
                          ("Beer Hall Levies", "2025-03")]:
        sl = df[(df["revenue_stream"] == stream) & (df["date"].str.startswith(month))]
        raw_drop = sl["actual_revenue"].sum() / df[df["revenue_stream"] == stream].groupby("date")[
            "actual_revenue"].sum().mean() - 1.0
        print(f"{stream:<18} {month}: raw vs average month {raw_drop:+6.1%}   "
              f"but deviation vs expected {sl['deviation_pct'].mean():+5.1f}%")


if __name__ == "__main__":
    main()
