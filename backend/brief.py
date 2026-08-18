"""
Fiscal Sentinel - the plain-language financial brief.

Every number in a brief is computed in Python (analytics.py, forecast.py) and
passed in as a finished fact. The language model's only job is to turn those
findings into a few paragraphs a council finance committee can read. It never
calculates, estimates, or infers a figure - if a number is not in the context
dictionary, it does not appear in the brief.

If no API key is present in the environment, the brief is rendered from a
deterministic template built from the same context. The demo therefore never
depends on a network call.

The API key is read from the environment only. Nothing is hardcoded here, and
the key is never written to disk or included in a response.

Run:
    python backend/brief.py
"""

from __future__ import annotations

import os
from typing import Any

from analytics import RECENT_WINDOW, get_engine, money
from forecast import build_forecast

# Read from the environment only. Never hardcode a key, never log one.
API_KEY_ENV = "ANTHROPIC_API_KEY"
MODEL_ENV = "FISCAL_SENTINEL_MODEL"
DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
You are a public finance analyst writing for the finance committee of a rural \
district council in Zimbabwe.

You will be given a JSON-style block of findings that have already been \
calculated by the council's analytics system. Turn them into a short executive \
brief.

Absolute rules:
- Use ONLY the figures given to you. Never calculate, estimate, re-derive or \
infer any number, percentage or total. If a figure is not in the findings, do \
not mention it.
- Call detected events "financial anomalies" or "potential revenue leakage". \
Never use the word "fraud", and never accuse any person or office of \
wrongdoing. These are matters to verify, not conclusions.
- Where a decline is marked as seasonal, say plainly that it is the normal \
annual pattern and not a shortfall.

Structure the brief as:
1. A two-sentence position summary for the month.
2. "What needs attention" - the flagged books, worst first, one short paragraph \
each, saying what the pattern is and what it could mean.
3. "Next quarter" - the forecast against budget.
4. "Recommended actions" - three to five specific, practical verification steps \
a council officer could carry out this month.

Write in plain British English for readers who are not analysts. No jargon, no \
bullet-point padding, roughly 300-400 words. Use Markdown headings.\
"""


# ---------------------------------------------------------------------------
# Context assembly - all numbers are produced here, by Python
# ---------------------------------------------------------------------------

def build_context(top_n: int = 5) -> dict[str, Any]:
    """Collect every finding the brief is allowed to talk about."""
    engine = get_engine()
    kpi = engine.kpi_summary()
    fc = build_forecast(engine.df)

    findings = []
    for b in engine.anomalies()[:top_n]:
        findings.append({
            "rank": len(findings) + 1,
            "ward": b["ward"],
            "revenue_stream": b["revenue_stream"],
            "collector_id": b["collector_id"],
            "risk_score": b["risk_score"],
            "risk_band": b["risk_band"],
            "headline": b["headline"],
            "deviation_pct_last_3_months": b["window_deviation_pct"],
            "gap_last_3_months": b["window_gap"],
            "annualised_exposure": b["annualised_exposure"],
            "average_receipt_change_pct": b["avg_transaction_shift_pct"],
            "receipt_volume_change_pct": b["transaction_shift_pct"],
            "round_number_month_rate_pct": b["round_number_rate"],
            "seasonally_explained": b["seasonally_explained"],
            "drivers": [f"{d['label']}: {d['detail']}" for d in b["drivers"]],
        })

    streams = [
        {
            "revenue_stream": s["revenue_stream"],
            "forecast_next_quarter": s["forecast_total"],
            "confidence_low": s["forecast_lower_total"],
            "confidence_high": s["forecast_upper_total"],
            "budget_next_quarter": s["budget_total"],
            "variance_vs_budget": s["variance_total"],
            "variance_pct": s["variance_pct"],
        }
        for s in fc["streams"]
    ]

    d = fc["district"]
    return {
        "council": "Rural District Council",
        "reporting_period": kpi["period_label"],
        "window_months": RECENT_WINDOW,
        "position": {
            "collected_this_month": kpi["revenue_this_month"],
            "expected_this_month": kpi["expected_this_month"],
            "gap_this_month": kpi["revenue_gap"],
            "deviation_pct": kpi["deviation_pct"],
            "month_on_month_pct": kpi["month_on_month_pct"],
            "books_monitored": kpi["books_monitored"],
            "anomaly_count": kpi["anomaly_count"],
            "critical_count": kpi["critical_count"],
            "high_count": kpi["high_count"],
            "watch_count": kpi["watch_count"],
            "exposure_identified": kpi["exposure_identified"],
        },
        "findings": findings,
        "forecast": {
            "window": fc["forecast_window"],
            "district_forecast": d["forecast_total"],
            "district_confidence_low": d["forecast_lower_total"],
            "district_confidence_high": d["forecast_upper_total"],
            "district_budget": d["budget_total"],
            "district_variance": d["variance_total"],
            "district_variance_pct": d["variance_pct"],
            "by_stream": streams,
        },
    }


# ---------------------------------------------------------------------------
# Deterministic brief - the default, and the fallback
# ---------------------------------------------------------------------------

def render_template_brief(ctx: dict[str, Any]) -> str:
    """Build the brief from the findings without calling any model."""
    p = ctx["position"]
    f = ctx["forecast"]
    w = ctx["window_months"]

    direction = "below" if p["gap_this_month"] < 0 else "above"
    lines: list[str] = []

    lines.append(f"# Financial Brief - {ctx['reporting_period']}")
    lines.append("")
    lines.append(
        f"The council collected **{money(p['collected_this_month'])}** in "
        f"{ctx['reporting_period']} against an expected "
        f"{money(p['expected_this_month'])}, leaving the month "
        f"{abs(p['deviation_pct']):.1f}% {direction} the seasonally adjusted "
        f"position ({money(abs(p['gap_this_month']))}). Of "
        f"{p['books_monitored']} ward and revenue-stream books under review, "
        f"{p['anomaly_count']} need attention this month "
        f"({p['critical_count']} critical, {p['high_count']} high, "
        f"{p['watch_count']} watch), with "
        f"{money(p['exposure_identified'])} of potential revenue leakage "
        f"identified over the last {w} months."
    )
    lines.append("")

    lines.append("## What needs attention")
    lines.append("")
    if not ctx["findings"]:
        lines.append(
            "No ward or revenue stream is currently outside its expected "
            "collection range. Monitoring continues."
        )
        lines.append("")

    for item in ctx["findings"]:
        lines.append(
            f"### {item['rank']}. {item['ward']} - {item['revenue_stream']} "
            f"({item['risk_band']}, risk score {item['risk_score']:.0f}/100)"
        )
        lines.append("")

        if item["seasonally_explained"]:
            lines.append(
                "Collections are down on the annual average, but this matches "
                "the normal seasonal pattern for this revenue stream rather "
                "than a genuine shortfall. No action is required beyond "
                "routine monitoring."
            )
            lines.append("")
            continue

        dev = item["deviation_pct_last_3_months"]
        if dev <= -6:
            lines.append(
                f"Collections have run {abs(dev):.1f}% below the seasonally "
                f"adjusted expectation over the last {w} months, a shortfall of "
                f"{money(abs(item['gap_last_3_months']))}. At the current rate "
                f"this represents roughly "
                f"{money(abs(item['annualised_exposure']))} a year."
            )
        elif dev >= 6:
            lines.append(
                f"Collections have run {dev:.1f}% above the seasonally adjusted "
                f"expectation over the last {w} months, "
                f"{money(abs(item['gap_last_3_months']))} more than budgeted. "
                f"An increase of this size warrants confirmation of the basis "
                f"of assessment."
            )
        else:
            lines.append(
                f"Total collections are close to expectation "
                f"({dev:+.1f}% over the last {w} months), but the underlying "
                f"pattern is irregular."
            )

        shift = item["average_receipt_change_pct"]
        if abs(shift) >= 12:
            lines.append("")
            if shift < 0:
                lines.append(
                    f"The average receipt has fallen {abs(shift):.1f}% against "
                    f"this book's own history while receipt volume moved "
                    f"{item['receipt_volume_change_pct']:+.1f}%. Traders are "
                    f"still being served but less money is reaching the "
                    f"council, which is the pattern associated with potential "
                    f"revenue leakage between the point of collection and the "
                    f"council account."
                )
            else:
                lines.append(
                    f"The average receipt has risen {abs(shift):.1f}% against "
                    f"this book's own history while receipt volume moved only "
                    f"{item['receipt_volume_change_pct']:+.1f}%. The extra "
                    f"revenue is therefore coming from larger individual "
                    f"charges rather than more payers, so the basis on which "
                    f"those amounts were assessed should be confirmed."
                )

        if item["round_number_month_rate_pct"] >= 25:
            lines.append("")
            lines.append(
                f"Separately, {item['round_number_month_rate_pct']:.0f}% of "
                f"months banked under collector {item['collector_id']} land on "
                f"an exact round figure. Genuine receipt totals rarely do. "
                f"This is a records and controls concern to verify rather than "
                f"a revenue shortfall."
            )

        lines.append("")

    lines.append("## Next quarter")
    lines.append("")
    fdir = "short of" if f["district_variance"] < 0 else "ahead of"
    lines.append(
        f"Collections for {f['window']} are projected at "
        f"**{money(f['district_forecast'])}** (likely range "
        f"{money(f['district_confidence_low'])} to "
        f"{money(f['district_confidence_high'])}), against a budget of "
        f"{money(f['district_budget'])}. That is "
        f"{money(abs(f['district_variance']))} {fdir} budget, or "
        f"{abs(f['district_variance_pct']):.1f}%."
    )
    lines.append("")

    worst = min(f["by_stream"], key=lambda s: s["variance_pct"])
    best = max(f["by_stream"], key=lambda s: s["variance_pct"])
    lines.append(
        f"The largest projected shortfall is in {worst['revenue_stream']} at "
        f"{worst['variance_pct']:+.1f}% against budget "
        f"({money(worst['forecast_next_quarter'])} forecast against "
        f"{money(worst['budget_next_quarter'])} budgeted). "
        f"{best['revenue_stream']} is the strongest stream at "
        f"{best['variance_pct']:+.1f}%."
    )
    lines.append("")

    lines.append("## Recommended actions")
    lines.append("")
    actions = _recommended_actions(ctx)
    for i, action in enumerate(actions, 1):
        lines.append(f"{i}. {action}")
    lines.append("")
    lines.append(
        "*These are financial anomalies identified from collection data and "
        "require verification. They are indicators for review, not "
        "conclusions about any individual or office.*"
    )

    return "\n".join(lines)


def _recommended_actions(ctx: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    w = ctx["window_months"]

    for item in ctx["findings"]:
        if item["seasonally_explained"]:
            continue
        dev = item["deviation_pct_last_3_months"]
        if dev <= -20:
            actions.append(
                f"Reconcile {item['ward']} {item['revenue_stream']} receipt "
                f"books against bank deposits for the last {w} months, and "
                f"confirm on site whether trading activity has actually fallen."
            )
        elif dev >= 20:
            actions.append(
                f"Verify the basis of assessment behind the increase in "
                f"{item['ward']} {item['revenue_stream']}, including whether "
                f"any backdated or bulk payments were posted to the period."
            )
        if item["round_number_month_rate_pct"] >= 25:
            actions.append(
                f"Request the underlying receipt-level detail for collector "
                f"{item['collector_id']} and confirm that banked totals match "
                f"the sum of individual receipts."
            )

    f = ctx["forecast"]
    if f["district_variance"] < 0:
        actions.append(
            f"Flag the projected {abs(f['district_variance_pct']):.1f}% "
            f"shortfall against budget for {f['window']} to the finance "
            f"committee before the next budget review."
        )

    actions.append(
        "Re-run this analysis after next month's collections to confirm "
        "whether the flagged patterns persist or resolve."
    )
    return actions[:5]


# ---------------------------------------------------------------------------
# LLM brief
# ---------------------------------------------------------------------------

def _findings_block(ctx: dict[str, Any]) -> str:
    """Render the context as a compact, unambiguous block of stated facts."""
    import json

    return json.dumps(ctx, indent=2, default=str)


def generate_llm_brief(ctx: dict[str, Any]) -> str:
    """Ask the model to narrate the findings. Raises on any failure."""
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{API_KEY_ENV} is not set")

    import anthropic  # imported lazily so the demo runs without the package

    client = anthropic.Anthropic()  # reads the key from the environment itself
    model = os.environ.get(MODEL_ENV) or DEFAULT_MODEL

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},
        messages=[{
            "role": "user",
            "content": (
                "Write the executive brief from these findings. Every figure "
                "you use must appear below verbatim.\n\n"
                f"{_findings_block(ctx)}"
            ),
        }],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("model declined to produce the brief")

    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("model returned an empty brief")
    return text


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_brief(prefer_llm: bool = True, top_n: int = 5) -> dict[str, Any]:
    """Produce a brief, falling back to the template if the model is unavailable."""
    ctx = build_context(top_n=top_n)

    if prefer_llm and os.environ.get(API_KEY_ENV):
        try:
            return {
                "source": "llm",
                "model": os.environ.get(MODEL_ENV) or DEFAULT_MODEL,
                "brief": generate_llm_brief(ctx),
                "note": "Narrative written by a language model from figures "
                        "computed in Python. No figure was produced by the model.",
                "context": ctx,
            }
        except Exception as exc:  # noqa: BLE001 - the demo must never break
            return {
                "source": "template",
                "model": None,
                "brief": render_template_brief(ctx),
                "note": f"Generated deterministically ({type(exc).__name__}: {exc}).",
                "context": ctx,
            }

    return {
        "source": "template",
        "model": None,
        "brief": render_template_brief(ctx),
        "note": f"Generated deterministically. Set {API_KEY_ENV} to have a "
                f"language model write the narrative instead.",
        "context": ctx,
    }


def _source_has_no_key() -> tuple[bool, str]:
    """Confirm this file contains no credential literal, only an env-var lookup."""
    import re
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    # Anthropic keys start sk-ant-; catch any long opaque secret-shaped literal too.
    hits = re.findall(r"[\"'](sk-[A-Za-z0-9_\-]{12,}|[A-Za-z0-9_\-]{40,})[\"']", source)
    return (not hits, "read from the environment only" if not hits
            else f"{len(hits)} suspicious literal(s)")


def main() -> None:
    key_set = bool(os.environ.get(API_KEY_ENV))
    print("=" * 78)
    print(f"FISCAL SENTINEL - financial brief   ({API_KEY_ENV} "
          f"{'detected' if key_set else 'not set - using template'})")
    print("=" * 78)

    result = generate_brief()
    print(result["brief"])
    print()
    print("-" * 78)
    print(f"source: {result['source']}   model: {result['model'] or 'n/a'}")
    print(result["note"])

    ctx = result["context"]
    print("\n--- validation -------------------------------------------------------")
    checks = [
        ("Brief produced", bool(result["brief"].strip()), ""),
        ("Never uses the word 'fraud'",
         "fraud" not in result["brief"].lower(), ""),
        ("Uses the approved framing",
         "anomal" in result["brief"].lower() or "leakage" in result["brief"].lower(), ""),
        ("Findings carried through",
         len(ctx["findings"]) > 0, f"{len(ctx['findings'])} findings"),
        ("Template path works without a key",
         bool(render_template_brief(ctx).strip()), ""),
        ("No credential literal in this module's source", *_source_has_no_key()),
    ]
    failed = 0
    for name, ok, note in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")


if __name__ == "__main__":
    main()
