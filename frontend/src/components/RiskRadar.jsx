import { bandStyle, pct } from "../format";

const BAND_ORDER = ["Critical", "High", "Watch", "Normal"];

function BandBadge({ band }) {
  const s = bandStyle(band);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${s.bg} ${s.text} ring-1 ${s.ring}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} aria-hidden="true" />
      {s.label}
    </span>
  );
}

export default function RiskRadar({ items, selectedId, onSelect }) {
  return (
    <div className="rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card)] flex flex-col h-full min-h-0">
      <div className="px-4 py-3 border-b border-[var(--border-hairline)] flex items-center justify-between shrink-0">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            Financial Risk Radar
          </h2>
          <p className="text-xs text-[var(--text-muted)]">
            Every ward and revenue stream, highest risk first
          </p>
        </div>
        <div className="hidden sm:flex items-center gap-2">
          {BAND_ORDER.map((b) => (
            <BandBadge key={b} band={b} />
          ))}
        </div>
      </div>

      <div className="overflow-y-auto flex-1 min-h-0">
        <ul className="divide-y divide-[var(--gridline)]">
          {items.map((item) => {
            const active = item.id === selectedId;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onSelect(item.id)}
                  className={`w-full text-left px-4 py-3 flex items-center gap-3 transition-colors hover:bg-black/[0.02] ${
                    active ? "bg-[var(--series-actual)]/[0.06]" : ""
                  }`}
                >
                  <div className="w-10 text-right shrink-0">
                    <span className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">
                      {item.risk_score.toFixed(0)}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-[var(--text-primary)] truncate">
                      {item.ward} · {item.revenue_stream}
                    </div>
                    <div className="text-xs text-[var(--text-muted)] truncate">
                      {item.seasonally_explained
                        ? "Seasonal pattern, within expectation"
                        : pct(item.deviation_pct, { signed: true }) + " vs expected"}
                    </div>
                  </div>
                  <BandBadge band={item.risk_band} />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
