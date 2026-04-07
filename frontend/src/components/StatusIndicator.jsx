import { STATUS_COLORS, STATUS_ICONS, STATUS_LABELS } from "../lib/constants";

export default function StatusIndicator({ status, size = "sm", showLabel = false }) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  const icon = STATUS_ICONS[status] || STATUS_ICONS.unknown;
  const label = STATUS_LABELS[status] || "Unknown";
  const shouldPulse = status !== "operational" && status !== "unknown";

  const iconSize = size === "md" ? "text-sm" : "text-xs";

  return (
    <span className="inline-flex items-center gap-1.5 shrink-0">
      <span
        className={`${iconSize} leading-none ${shouldPulse ? "animate-pulse" : ""}`}
        style={{ color }}
        role="img"
        aria-label={label}
      >
        {icon}
      </span>
      {showLabel && (
        <span className="text-xs font-medium" style={{ color }}>
          {label}
        </span>
      )}
    </span>
  );
}
