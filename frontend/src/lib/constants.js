import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  AlertOctagon,
  XOctagon,
  HelpCircle,
  WifiOff,
} from "lucide-react";

export const STATUS_COLORS = {
  operational: "#34d399",
  degraded: "#fbbf24",
  partial_outage: "#fb923c",
  major_outage: "#f87171",
  unknown: "#6b7280",
};

// RGBA tints for tile backgrounds — punched up
export const STATUS_TINTS = {
  operational: "rgba(52, 211, 153, 0.15)",
  degraded: "rgba(251, 191, 36, 0.18)",
  partial_outage: "rgba(251, 146, 60, 0.18)",
  major_outage: "rgba(248, 113, 113, 0.20)",
  unknown: "rgba(107, 114, 128, 0.08)",
};

// Hover tints — noticeably brighter
export const STATUS_TINTS_HOVER = {
  operational: "rgba(52, 211, 153, 0.25)",
  degraded: "rgba(251, 191, 36, 0.30)",
  partial_outage: "rgba(251, 146, 60, 0.30)",
  major_outage: "rgba(248, 113, 113, 0.32)",
  unknown: "rgba(107, 114, 128, 0.15)",
};

export const STATUS_LABELS = {
  operational: "Operational",
  degraded: "Degraded",
  partial_outage: "Partial Outage",
  major_outage: "Major Outage",
  unknown: "Unknown",
};

// Lucide icon components — distinct shape AND color so tiles read for
// colorblind users and screen readers alike (WCAG 1.4.1, "Use of Color").
// Each status has a visually-distinct shape: circle/triangle/octagon/X/?.
export const STATUS_ICON_COMPONENTS = {
  operational: CheckCircle2,
  degraded: AlertTriangle,
  partial_outage: AlertOctagon,
  major_outage: XOctagon,
  unknown: HelpCircle,
};

// Icon for the poller-is-broken variant of "unknown" — tells the operator
// "we can't reach the vendor" rather than "the vendor hasn't told us yet".
export const POLLER_BROKEN_ICON = WifiOff;

// Icon for the mid-flap "unstable" badge — signals the pending state machine
// is accumulating polls toward a status change, but hasn't confirmed it yet.
export const FLAPPING_ICON = Activity;

// Kept for places we still want a one-char inline marker (e.g., chips).
export const STATUS_ICONS = {
  operational: "✓",
  degraded: "⚠",
  partial_outage: "●",
  major_outage: "✕",
  unknown: "?",
};

// Severity rank used for sorting worst-first. Unknown is ranked between
// operational and degraded because its meaning varies: a fresh boot is
// better than degraded; a broken poller is worse than operational. The
// poller_health signal (below) lets the grid distinguish the two.
export const STATUS_SEVERITY_RANK = {
  major_outage: 4,
  partial_outage: 3,
  degraded: 2,
  unknown: 1,
  operational: 0,
};

export const POLLER_HEALTH_LABELS = {
  healthy: "Poller healthy",
  degraded: "Poller degraded",
  broken: "Poller broken — readings may be stale",
};

export const CATEGORY_ORDER = [
  { key: "identity", label: "Identity & Access" },
  { key: "productivity", label: "Productivity" },
  { key: "collaboration", label: "Collaboration" },
  { key: "engineering", label: "Engineering" },
  { key: "hr", label: "HR & People" },
  { key: "finance", label: "Finance" },
  { key: "sales", label: "Sales & CRM" },
  { key: "marketing", label: "Marketing" },
  { key: "support", label: "Support" },
];

export const SEVERITY_COLORS = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#f59e0b",
  low: "#6b7280",
};

export const POLL_INTERVAL_MS = 30_000;
export const UPTIME_POLL_INTERVAL_MS = 300_000;
export const STALE_WARNING_MS = 90_000;
export const STALE_CRITICAL_MS = 180_000;

/** Compute the effective status we should render for a service.
 *
 * If the poller is broken we force `unknown` — rendering `operational`
 * while we're actually blind is the single worst dashboard UX bug.
 * Recoveries from broken (unknown→operational) bubble through via the
 * normal poll path. */
export function effectiveStatus(service) {
  if (!service) return "unknown";
  if (service.poller_health === "broken") return "unknown";
  return service.current_status || "unknown";
}

/** Is this service in the "we can't reach the vendor" state? */
export function isPollerBroken(service) {
  return service?.poller_health === "broken";
}

/** Is this service mid-flap — pending a status change that hasn't been confirmed yet?
 *
 * Returns true when the backend's pending-state buffer has accumulated at least
 * one poll pointing at a *different* status than the committed current_status.
 * The badge reuses STATUS_COLORS.degraded (yellow) because yellow already means
 * "watch this" in our palette, and adding a new colour token would weaken the
 * signal hierarchy. */
export function isFlapping(service) {
  return Boolean(
    service?.pending_status && service.pending_status !== service.current_status,
  );
}
