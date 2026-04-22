import {
  POLLER_BROKEN_ICON,
  POLLER_HEALTH_LABELS,
  STATUS_COLORS,
  STATUS_ICON_COMPONENTS,
  STATUS_LABELS,
} from "../lib/constants";

/**
 * Render a status tile indicator with:
 *   - distinct icon shape per status (WCAG 1.4.1)
 *   - status color (redundant with shape, not sole signal)
 *   - aria-label for screen readers
 *
 * `pollerBroken` overrides the icon to WifiOff and the label to
 * "Poller broken — readings may be stale", regardless of the underlying
 * `status`. That separation prevents the dashboard from rendering
 * `operational` when the poller itself is offline.
 */
export default function StatusIndicator({
  status,
  size = "sm",
  showLabel = false,
  pollerBroken = false,
}) {
  const color = pollerBroken
    ? STATUS_COLORS.unknown
    : STATUS_COLORS[status] || STATUS_COLORS.unknown;

  const Icon = pollerBroken
    ? POLLER_BROKEN_ICON
    : STATUS_ICON_COMPONENTS[status] || STATUS_ICON_COMPONENTS.unknown;

  const label = pollerBroken
    ? POLLER_HEALTH_LABELS.broken
    : STATUS_LABELS[status] || "Unknown";

  const shouldPulse = !pollerBroken && status !== "operational" && status !== "unknown";
  const iconPx = size === "md" ? 16 : 14;

  return (
    <span className="inline-flex items-center gap-1.5 shrink-0">
      <span
        className={`inline-flex ${shouldPulse ? "animate-pulse" : ""}`}
        style={{ color }}
        role="img"
        aria-label={label}
      >
        <Icon size={iconPx} strokeWidth={2.5} />
      </span>
      {showLabel && (
        <span className="text-xs font-medium" style={{ color }}>
          {label}
        </span>
      )}
    </span>
  );
}
