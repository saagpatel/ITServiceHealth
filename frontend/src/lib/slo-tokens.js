export const SLO_POLL_INTERVAL_MS = 5 * 60 * 1000;

// Zone thresholds — breakpoints on error_budget_remaining_pct.
// If fast_burning is true, force the critical (red) zone regardless of budget.
export const SLO_ZONES = [
  { min: 50, max: 100, id: "healthy",  color: "#34d399" },   // --color-status-operational
  { min: 20, max: 50,  id: "warning",  color: "#fbbf24" },   // --color-status-degraded
  { min: 0,  max: 20,  id: "critical", color: "#ef4444" },   // --color-accent-alarm
];

export function pickZone(budgetPct, isFastBurning) {
  if (isFastBurning) return SLO_ZONES[2];
  for (const z of SLO_ZONES) {
    if (budgetPct >= z.min && budgetPct <= z.max) return z;
  }
  return SLO_ZONES[0];
}

export function formatBurnRate(rate) {
  return typeof rate === "number" && Number.isFinite(rate) ? `${rate.toFixed(1)}x` : "—";
}

export function formatBudgetPct(pct) {
  return typeof pct === "number" && Number.isFinite(pct) ? `${Math.round(pct)}%` : "—";
}
