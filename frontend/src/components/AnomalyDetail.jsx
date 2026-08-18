import {
  Line,
  LineChart,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { bandStyle, money, pct } from "../format";

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-[var(--border-hairline)] bg-[var(--surface-card)] px-3 py-2 shadow-sm text-xs">
      <div className="font-medium text-[var(--text-primary)] mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-[var(--text-secondary)]">
          <span
            className="h-2 w-2 rounded-full shrink-0"
            style={{ background: p.color }}
          />
          <span className="capitalize">{p.name}</span>
          <span className="ml-auto tabular-nums font-medium text-[var(--text-primary)]">
            {money(p.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function FlaggedDot(props) {
  const { cx, cy, payload } = props;
  if (!payload?.flagged) return null;
  return (
    <circle
      cx={cx}
      cy={cy}
      r={5}
      fill="var(--status-critical)"
      stroke="var(--surface-card)"
      strokeWidth={2}
    />
  );
}

export default function AnomalyDetail({ detail }) {
  if (!detail) {
    return (
      <div className="rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card)] h-full flex items-center justify-center text-sm text-[var(--text-muted)]">
        Select a ward and revenue stream from the Risk Radar to see its trend
      </div>
    );
  }

  const s = bandStyle(detail.risk_band);

  return (
    <div className="rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card)] p-4 flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {detail.ward} · {detail.revenue_stream}
          </h2>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${s.bg} ${s.text} ring-1 ${s.ring}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
            {s.label} · {detail.risk_score.toFixed(0)}/100
          </span>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mt-1">{detail.headline}</p>
      </div>

      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={detail.trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="var(--gridline)" strokeDasharray="0" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: "var(--text-muted)" }}
              axisLine={{ stroke: "var(--border-hairline)" }}
              tickLine={false}
              interval="preserveStartEnd"
              minTickGap={20}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "var(--text-muted)" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => money(v, { compact: true })}
              width={56}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              iconType="plainline"
              wrapperStyle={{ fontSize: 12, color: "var(--text-secondary)" }}
            />
            <Line
              type="monotone"
              dataKey="expected"
              name="Expected"
              stroke="var(--text-muted)"
              strokeWidth={2}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="actual"
              name="Actual"
              stroke="var(--series-actual)"
              strokeWidth={2}
              dot={<FlaggedDot />}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-[var(--text-muted)]">3-month deviation</div>
          <div className="font-semibold text-[var(--text-primary)] tabular-nums">
            {pct(detail.window_deviation_pct, { signed: true })}
          </div>
        </div>
        <div>
          <div className="text-[var(--text-muted)]">3-month gap</div>
          <div className="font-semibold text-[var(--text-primary)] tabular-nums">
            {money(detail.window_gap)}
          </div>
        </div>
        <div>
          <div className="text-[var(--text-muted)]">Collector</div>
          <div className="font-semibold text-[var(--text-primary)]">
            {detail.collector_id}
          </div>
        </div>
        <div>
          <div className="text-[var(--text-muted)]">Round-figure months</div>
          <div className="font-semibold text-[var(--text-primary)] tabular-nums">
            {pct(detail.round_number_rate)}
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wide">
          Why it's flagged
        </h3>
        <ul className="space-y-1.5">
          {detail.drivers.map((d, i) => (
            <li key={i} className="text-xs text-[var(--text-secondary)] flex gap-2">
              <span className="text-[var(--text-primary)] font-medium shrink-0">
                {d.label}:
              </span>
              <span>{d.detail}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
