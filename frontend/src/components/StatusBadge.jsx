import { STATUS_COLORS, STATUS_LABELS } from "../lib/constants";

export default function StatusBadge({ status, showLabel = false, size = "sm" }) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  const label = STATUS_LABELS[status] || "Unknown";
  const dotSize = size === "md" ? "w-2.5 h-2.5" : "w-2 h-2";
  const shouldPulse = status !== "operational" && status !== "unknown";

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`${dotSize} rounded-full shrink-0 ${shouldPulse ? "animate-pulse" : ""}`}
        style={{ backgroundColor: color }}
      />
      {showLabel && (
        <span className="text-xs" style={{ color }}>
          {label}
        </span>
      )}
    </span>
  );
}
