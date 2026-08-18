export function money(value, opts = {}) {
  const { compact = false } = opts;
  if (value == null || Number.isNaN(value)) return "-";
  if (compact) {
    const abs = Math.abs(value);
    if (abs >= 1_000_000) return `${value < 0 ? "-" : ""}$${(abs / 1_000_000).toFixed(1)}M`;
    if (abs >= 1_000) return `${value < 0 ? "-" : ""}$${(abs / 1_000).toFixed(1)}K`;
  }
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function pct(value, opts = {}) {
  const { signed = false } = opts;
  if (value == null || Number.isNaN(value)) return "-";
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

// Risk band -> status role, per the dataviz status palette (never themed).
export const BAND_STYLES = {
  Normal: {
    text: "text-[var(--status-good)]",
    dot: "bg-[var(--status-good)]",
    bg: "bg-[var(--status-good)]/10",
    ring: "ring-[var(--status-good)]/30",
    label: "Normal",
  },
  Watch: {
    text: "text-[#8a6300]",
    dot: "bg-[var(--status-warning)]",
    bg: "bg-[var(--status-warning)]/15",
    ring: "ring-[var(--status-warning)]/40",
    label: "Watch",
  },
  High: {
    text: "text-[#a1481f]",
    dot: "bg-[var(--status-serious)]",
    bg: "bg-[var(--status-serious)]/15",
    ring: "ring-[var(--status-serious)]/40",
    label: "High",
  },
  Critical: {
    text: "text-[var(--status-critical)]",
    dot: "bg-[var(--status-critical)]",
    bg: "bg-[var(--status-critical)]/10",
    ring: "ring-[var(--status-critical)]/30",
    label: "Critical",
  },
};

export function bandStyle(band) {
  return BAND_STYLES[band] || BAND_STYLES.Normal;
}
