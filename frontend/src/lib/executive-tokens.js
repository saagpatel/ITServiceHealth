export const EXEC_SLA_TARGET = 99.9;
export const EXEC_IMPACT_LIMIT = 8;

// recharts doesn't resolve CSS var() in SVG attributes reliably, so the
// chart needs raw hex. These MUST stay in lock-step with the @theme block
// in frontend/src/styles/index.css — if you change one, change both.
export const EXEC_CHART_COLORS = {
  surfaceElev2: "#1b2436",
  accentAlarm: "#ef4444",
  textDisplay: "#f8fafc",
  textDim: "#64748b",
};

export const STATUS_RANK = {
  major_outage: 4,
  partial_outage: 3,
  degraded: 2,
  unknown: 1,
  operational: 0,
};

export function formatSlaPct(n) {
  return typeof n === "number" && Number.isFinite(n) ? `${n.toFixed(2)}%` : "—";
}

export function formatDeltaBps(n) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  const rounded = Math.round(n);
  if (rounded === 0) return "±0 bps";
  const sign = rounded > 0 ? "+" : "−";
  return `${sign}${Math.abs(rounded)} bps`;
}
