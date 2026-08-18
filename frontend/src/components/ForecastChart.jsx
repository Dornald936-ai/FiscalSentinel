import { useMemo, useState } from "react";
import {
  Area,
  ComposedChart,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  Line,
  ResponsiveContainer,
} from "recharts";
import { money, pct } from "../format";

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const visible = payload.filter(
    (p) => p.dataKey === "actual" || p.dataKey === "budget" || p.dataKey === "forecast"
  );
  if (!visible.length) return null;
  return (
    <div className="rounded-md border border-[var(--border-hairline)] bg-[var(--surface-card)] px-3 py-2 shadow-sm text-xs">
      <div className="font-medium text-[var(--text-primary)] mb-1">{label}</div>
      {visible.map((p) =>
        p.value == null ? null : (
          <div
            key={p.dataKey}
            className="flex items-center gap-2 text-[var(--text-secondary)]"
          >
            <span className="h-2 w-2 rounded-full shrink-0" style={{ background: p.color }} />
            <span className="capitalize">{p.name}</span>
            <span className="ml-auto tabular-nums font-medium text-[var(--text-primary)]">
              {money(p.value)}
            </span>
          </div>
        )
      )}
    </div>
  );
}

export default function ForecastChart({ forecast }) {
  const streamNames = useMemo(
    () => (forecast ? forecast.streams.map((s) => s.revenue_stream) : []),
    [forecast]
  );
  const [selected, setSelected] = useState("All Revenue Streams");

  if (!forecast) return null;

  const active =
    selected === "All Revenue Streams"
      ? forecast.district
      : forecast.streams.find((s) => s.revenue_stream === selected);

  const chartData = active.series.map((p) => ({
    ...p,
    bandBase: p.lower,
    bandHeight: p.lower != null && p.upper != null ? p.upper - p.lower : null,
  }));

  return (
    <div className="rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card)] p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            Collections vs Forecast
          </h2>
          <p className="text-xs text-[var(--text-muted)]">
            {forecast.forecast_window} · {pct(active.variance_pct, { signed: true })} vs
            budget
          </p>
        </div>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="text-xs border border-[var(--border-hairline)] rounded-md px-2 py-1.5 bg-[var(--surface-card)] text-[var(--text-primary)]"
        >
          <option>All Revenue Streams</option>
          {streamNames.map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
      </div>

      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
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
              payload={[
                { value: "Actual", type: "plainline", color: "var(--series-actual)" },
                { value: "Budget", type: "plainline", color: "var(--text-muted)" },
                { value: "Forecast", type: "plainline", color: "var(--series-forecast)" },
              ]}
            />
            <Area
              dataKey="bandBase"
              stackId="band"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
            />
            <Area
              dataKey="bandHeight"
              name="Confidence range"
              stackId="band"
              stroke="none"
              fill="var(--series-forecast)"
              fillOpacity={0.12}
              isAnimationActive={false}
              legendType="none"
              tooltipType="none"
            />
            <Line
              type="monotone"
              dataKey="budget"
              name="Budget"
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
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
              connectNulls={false}
            />
            <Line
              type="monotone"
              dataKey="forecast"
              name="Forecast"
              stroke="var(--series-forecast)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-3 gap-3 text-xs">
        <div>
          <div className="text-[var(--text-muted)]">Forecast total</div>
          <div className="font-semibold text-[var(--text-primary)] tabular-nums">
            {money(active.forecast_total)}
          </div>
        </div>
        <div>
          <div className="text-[var(--text-muted)]">Budget total</div>
          <div className="font-semibold text-[var(--text-primary)] tabular-nums">
            {money(active.budget_total)}
          </div>
        </div>
        <div>
          <div className="text-[var(--text-muted)]">Range</div>
          <div className="font-semibold text-[var(--text-primary)] tabular-nums">
            {money(active.forecast_lower_total, { compact: true })} - {" "}
            {money(active.forecast_upper_total, { compact: true })}
          </div>
        </div>
      </div>
    </div>
  );
}
