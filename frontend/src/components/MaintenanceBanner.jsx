import { useState } from "react";
import { formatTimestamp } from "../lib/format";

export default function MaintenanceBanner({ data }) {
  const [expanded, setExpanded] = useState(false);

  if (!data?.upcoming_maintenances?.length) return null;

  const maintenances = data.upcoming_maintenances;
  const visible = expanded ? maintenances : maintenances.slice(0, 3);
  const remaining = maintenances.length - 3;

  return (
    <div className="bg-amber-950/50 border-b border-amber-900/30 px-4 py-2">
      <div className="flex items-center gap-2 mb-1">
        <svg className="w-3.5 h-3.5 text-status-degraded shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
        </svg>
        <span className="text-xs font-medium text-status-degraded">Scheduled Maintenance</span>
      </div>
      <div className="space-y-0.5">
        {visible.map((m) => (
          <div key={m.id} className="text-xs text-text-muted">
            <span className="text-text-secondary">{m.service_name}</span>
            {" — "}
            {m.title}
            {" — "}
            <span className="text-text-muted">{formatTimestamp(m.scheduled_for)}</span>
          </div>
        ))}
        {!expanded && remaining > 0 && (
          <button
            onClick={() => setExpanded(true)}
            className="text-xs text-accent hover:underline cursor-pointer"
          >
            +{remaining} more
          </button>
        )}
      </div>
    </div>
  );
}
