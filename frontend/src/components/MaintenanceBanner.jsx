import { useState } from "react";
import { formatTimestamp } from "../lib/format";

export default function MaintenanceBanner({ data }) {
  const [expanded, setExpanded] = useState(false);

  if (!data?.upcoming_maintenances?.length) return null;

  const maintenances = data.upcoming_maintenances;
  const visible = expanded ? maintenances : maintenances.slice(0, 3);
  const remaining = maintenances.length - 3;

  return (
    <div className="rounded-lg bg-bg-surface border border-border px-4 py-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left cursor-pointer"
      >
        <span className="text-xs">🔧</span>
        <span className="text-xs font-medium text-text-secondary">
          {maintenances.length} scheduled maintenance{maintenances.length !== 1 ? "s" : ""}
        </span>
        <svg
          className={`w-3 h-3 text-text-muted ml-auto transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1 border-t border-border pt-2">
          {visible.map((m) => (
            <div key={m.id} className="text-xs text-text-muted flex gap-2">
              <span className="text-text-secondary font-medium shrink-0">{m.service_name}</span>
              <span className="truncate">{m.title}</span>
              <span className="shrink-0 ml-auto">{formatTimestamp(m.scheduled_for)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
