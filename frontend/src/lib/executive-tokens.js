/**
 * Executive-view-only constants and formatters. Lives in lib/ so the
 * hook and the components can both import without circular dependencies.
 *
 * The SLA target is hardcoded here rather than env-driven because the
 * Executive view is a read-only artifact for a conference-room audience;
 * making it runtime-configurable adds operational surface area without
 * changing what a director sees on the screen. Defer to Phase 1 of a
 * follow-on roadmap if a tunable target is ever actually requested.
 */

export const EXEC_SLA_TARGET = 99.9;
export const EXEC_IMPACT_LIMIT = 8;

/** Format a 0-100 uptime percentage to two decimals. */
export function formatSlaPct(pct) {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return "—";
  return `${pct.toFixed(2)}%`;
}

/** Format a basis-points delta with sign + target context.
 *
 * +7 bps above target / −48 bps under target. Zero renders as "on target".
 */
export function formatDeltaBps(observed, target = EXEC_SLA_TARGET) {
  if (observed === null || observed === undefined || Number.isNaN(observed)) {
    return "—";
  }
  const bps = Math.round((observed - target) * 100);
  if (bps === 0) return "on target";
  const sign = bps > 0 ? "+" : "−";
  const magnitude = Math.abs(bps);
  const label = bps > 0 ? "above target" : "under target";
  return `${sign}${magnitude} bps ${label}`;
}
