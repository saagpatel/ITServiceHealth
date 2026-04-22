import { useState } from "react";
import {
  POLLER_BROKEN_ICON,
  POLLER_HEALTH_LABELS,
  STATUS_COLORS,
  STATUS_ICON_COMPONENTS,
  STATUS_LABELS,
  STATUS_TINTS,
  STATUS_TINTS_HOVER,
  effectiveStatus,
  isPollerBroken,
} from "../lib/constants";

/**
 * One service tile in the status grid.
 *
 * Three visually-distinct states:
 *   1. Monitored service (any status) — full-color tile, status icon +
 *      label, pulses if degraded/partial/major.
 *   2. Manually-tracked service that's never been updated — faded tile,
 *      "Manual" label; doesn't pulse.
 *   3. Poller broken — dashed border, WifiOff icon, "Poller broken —
 *      readings may be stale" tooltip. Status forced to `unknown`
 *      regardless of last-known value. This is the most important UX
 *      invariant: never render `operational` when we're flying blind.
 */
export default function ServiceTile({
  service,
  uptimePercent,
  onClick,
  onFocus,
  tabIndex = -1,
}) {
  const [hovered, setHovered] = useState(false);

  const isManual = service.poll_type === "manual";
  const pollerBroken = isPollerBroken(service);
  const isUnmonitored =
    isManual && service.current_status === "unknown" && !pollerBroken;

  const status = effectiveStatus(service);
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;

  const StatusIcon = pollerBroken
    ? POLLER_BROKEN_ICON
    : STATUS_ICON_COMPONENTS[status] || STATUS_ICON_COMPONENTS.unknown;

  const label = pollerBroken
    ? "Unknown"
    : isUnmonitored
    ? "Manual"
    : STATUS_LABELS[status] || "Unknown";

  const tint = isUnmonitored
    ? "rgba(107, 114, 128, 0.05)"
    : (hovered ? STATUS_TINTS_HOVER[status] : STATUS_TINTS[status]) ||
      STATUS_TINTS.unknown;

  const borderColor = isUnmonitored ? "transparent" : color;
  const shouldPulse =
    !pollerBroken &&
    status !== "operational" &&
    status !== "unknown" &&
    !isUnmonitored;

  // Uptime badge color
  let uptimeColor = "#64748b";
  if (uptimePercent !== null && uptimePercent !== undefined) {
    if (uptimePercent >= 99.9) uptimeColor = STATUS_COLORS.operational;
    else if (uptimePercent >= 99) uptimeColor = STATUS_COLORS.degraded;
    else uptimeColor = STATUS_COLORS.major_outage;
  }

  const tooltip = pollerBroken
    ? `${POLLER_HEALTH_LABELS.broken}${
        service.last_failure_reason ? `\n${service.last_failure_reason}` : ""
      }`
    : service.current_status_detail || label;

  const ariaLabel = pollerBroken
    ? `${service.display_name}: ${POLLER_HEALTH_LABELS.broken}`
    : `${service.display_name}: ${label}${
        service.current_status_detail ? `, ${service.current_status_detail}` : ""
      }`;

  return (
    <button
      data-service-id={service.id}
      role="gridcell"
      tabIndex={tabIndex}
      aria-label={ariaLabel}
      onClick={() => onClick(service.id)}
      onFocus={() => onFocus?.(service.id)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={tooltip}
      className={`relative text-left rounded-lg px-3.5 py-3 border-l-[3px]
                  transition-all duration-150 cursor-pointer
                  ${hovered ? "scale-[1.02]" : ""}
                  ${isUnmonitored ? "opacity-50" : ""}
                  ${pollerBroken ? "border-dashed" : ""}`}
      style={{
        backgroundColor: tint,
        borderLeftColor: borderColor,
      }}
    >
      <div className="flex items-start justify-between">
        <span
          className={`inline-flex ${shouldPulse ? "animate-pulse" : ""}`}
          style={{ color }}
        >
          <StatusIcon size={14} strokeWidth={2.5} />
        </span>
        {uptimePercent !== null && uptimePercent !== undefined && (
          <span
            className="text-[10px] font-medium"
            style={{ color: uptimeColor }}
            data-tabular="true"
          >
            {uptimePercent.toFixed(1)}%
          </span>
        )}
      </div>
      <div className="text-[13px] font-medium text-text-primary truncate mt-0.5">
        {service.display_name}
      </div>
      <div
        className="text-[11px] mt-0.5"
        style={{ color: isUnmonitored ? "#64748b" : color }}
      >
        {label}
      </div>
    </button>
  );
}
