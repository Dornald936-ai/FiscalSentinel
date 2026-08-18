import { money, pct } from "../format";

function StatTile({ label, value, delta, deltaGood, sub }) {
  return (
    <div className="rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card)] p-4 flex flex-col gap-1 min-w-0">
      <div className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide truncate">
        {label}
      </div>
      <div className="text-2xl font-semibold text-[var(--text-primary)] truncate">
        {value}
      </div>
      {(delta || sub) && (
        <div className="text-xs text-[var(--text-secondary)] flex items-center gap-1">
          {delta && (
            <span
              className={
                deltaGood === true
                  ? "text-[var(--status-good)]"
                  : deltaGood === false
                    ? "text-[var(--status-critical)]"
                    : "text-[var(--text-secondary)]"
              }
            >
              {delta}
            </span>
          )}
          {sub && <span>{sub}</span>}
        </div>
      )}
    </div>
  );
}

export default function KpiCards({ kpis }) {
  if (!kpis) return null;

  const gapGood = kpis.revenue_gap >= 0;
  const momGood = kpis.month_on_month_pct >= 0;
  const forecastGood = kpis.next_quarter_variance_pct >= 0;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      <StatTile
        label={`Revenue - ${kpis.period_label}`}
        value={money(kpis.revenue_this_month)}
        delta={pct(kpis.month_on_month_pct, { signed: true })}
        deltaGood={momGood}
        sub="vs last month"
      />
      <StatTile
        label="Expected revenue"
        value={money(kpis.expected_this_month)}
        sub="seasonally adjusted"
      />
      <StatTile
        label="Revenue gap"
        value={money(kpis.revenue_gap)}
        delta={pct(kpis.deviation_pct, { signed: true })}
        deltaGood={gapGood}
        sub="vs expected"
      />
      <StatTile
        label="Anomalies flagged"
        value={String(kpis.anomaly_count)}
        sub={`${kpis.critical_count} critical, ${kpis.high_count} high`}
      />
      <StatTile
        label="Next quarter forecast"
        value={money(kpis.next_quarter_forecast, { compact: true })}
        delta={pct(kpis.next_quarter_variance_pct, { signed: true })}
        deltaGood={forecastGood}
        sub="vs budget"
      />
    </div>
  );
}
