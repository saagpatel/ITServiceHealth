import StatusBadge from "./StatusBadge";
import { STATUS_COLORS } from "../lib/constants";

export default function ServiceCard({ service, isSelected, onClick }) {
  const borderColor = isSelected
    ? STATUS_COLORS[service.current_status] || STATUS_COLORS.unknown
    : "transparent";

  return (
    <button
      onClick={() => onClick(service.id)}
      title={service.current_status_detail || service.current_status}
      className="flex items-center gap-2 px-3 py-2 bg-bg-card border border-border rounded text-left
                 hover:bg-bg-hover transition-colors w-full cursor-pointer"
      style={{ borderLeftWidth: "2px", borderLeftColor: borderColor }}
    >
      <StatusBadge status={service.current_status} />
      <span className="text-sm text-text-primary truncate">{service.display_name}</span>
    </button>
  );
}
