import { useState } from "react";
import { STATUS_COLORS, STATUS_TINTS, STATUS_TINTS_HOVER, STATUS_LABELS, STATUS_ICONS } from "../lib/constants";

export default function ServiceTile({ service, uptimePercent, onClick }) {
  const [hovered, setHovered] = useState(false);

  const isManual = service.poll_type === "manual";
  const isUnmonitored = isManual && service.current_status === "unknown";
  const status = service.current_status;

  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  const icon = isUnmonitored ? "—" : (STATUS_ICONS[status] || "—");
  const label = isUnmonitored ? "Manual" : (STATUS_LABELS[status] || "Unknown");
  const tint = isUnmonitored
    ? "rgba(107, 114, 128, 0.05)"
    : (hovered ? STATUS_TINTS_HOVER[status] : STATUS_TINTS[status]) || STATUS_TINTS.unknown;
  const borderColor = isUnmonitored ? "transparent" : color;
  const shouldPulse = status !== "operational" && status !== "unknown" && !isUnmonitored;

  // Uptime badge color
  let uptimeColor = "#64748b";
  if (uptimePercent !== null && uptimePercent !== undefined) {
    if (uptimePercent >= 99.9) uptimeColor = STATUS_COLORS.operational;
    else if (uptimePercent >= 99) uptimeColor = STATUS_COLORS.degraded;
    else uptimeColor = STATUS_COLORS.major_outage;
  }

  return (
    <button
      onClick={() => onClick(service.id)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={service.current_status_detail || label}
      className={`relative text-left rounded-lg px-3.5 py-3 border-l-[3px]
                  transition-all duration-150 cursor-pointer
                  ${hovered ? "scale-[1.02]" : ""}
                  ${isUnmonitored ? "opacity-50" : ""}`}
      style={{
        backgroundColor: tint,
        borderLeftColor: borderColor,
      }}
    >
      <div className="flex items-start justify-between">
        <div className={`text-sm ${shouldPulse ? "animate-pulse" : ""}`} style={{ color }}>
          {icon}
        </div>
        {uptimePercent !== null && uptimePercent !== undefined && (
          <span className="text-[10px] font-medium" style={{ color: uptimeColor }}>
            {uptimePercent.toFixed(1)}%
          </span>
        )}
      </div>
      <div className="text-[13px] font-medium text-text-primary truncate mt-0.5">
        {service.display_name}
      </div>
      <div className="text-[11px] mt-0.5" style={{ color: isUnmonitored ? "#64748b" : color }}>
        {label}
      </div>
    </button>
  );
}
