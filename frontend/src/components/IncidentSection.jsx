import StatusIndicator from "./StatusIndicator";
import { STATUS_COLORS } from "../lib/constants";
import { timeAgo } from "../lib/format";

export default function IncidentSection({ incidents }) {
  if (!incidents || incidents.length === 0) return null;

  return (
    <div className="space-y-2">
      {incidents.map((incident) => (
        <div
          key={incident.service.id}
          className="rounded-lg bg-bg-surface border-l-[3px] px-4 py-3"
          style={{ borderLeftColor: STATUS_COLORS[incident.service.current_status] || STATUS_COLORS.degraded }}
        >
          <div className="flex items-center gap-2">
            <StatusIndicator status={incident.service.current_status} size="sm" />
            <span className="text-sm font-semibold text-text-primary">
              {incident.service.display_name}
            </span>
            <span className="text-xs text-text-muted ml-auto">
              {incident.started_at ? timeAgo(incident.started_at) : ""}
            </span>
          </div>
          {incident.impact_statement && (
            <p className="text-xs text-text-secondary mt-1.5 ml-5 leading-relaxed">
              {incident.impact_statement}
            </p>
          )}
          {incident.affected_services && incident.affected_services.length > 0 && (
            <p className="text-xs text-text-muted mt-1 ml-5">
              May impact: {incident.affected_services.join(", ")}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
