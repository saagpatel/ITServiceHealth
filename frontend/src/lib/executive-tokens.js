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

/** Hex mirror of the Executive-view CSS custom properties.
 *
 *  recharts (and SVG in general) cannot resolve var(--color-*) in its
 *  stroke/fill attributes, so the exec components pass real hex values
 *  for chart internals. These MUST stay in sync with the @theme block
 *  in frontend/src/styles/index.css — if a token moves here, it moves
 *  there too. The zero-hex rule still holds inside
 *  frontend/src/components/executive/ because the hex lives here, not
 *  inside the components. */
export const EXEC_TREND_COLORS = Object.freeze({
  accentAlarm: "#ef4444",
  surfaceElev1: "#0f172a",
  surfaceElev2: "#1b2436",
  textDim: "#64748b",
  textDisplay: "#f8fafc",
  border: "#1e293b",
});

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
