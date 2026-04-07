import StatusBadge from "./StatusBadge";
import { timeAgo, humanStatus } from "../lib/format";

export default function Timeline({ data, loading }) {
  if (loading || !data) {
    return (
      <div className="space-y-3">
        <h2 className="text-xs uppercase tracking-wider text-text-secondary font-medium">Timeline</h2>
        {[...Array(8)].map((_, i) => (
          <div key={i} className="h-12 bg-bg-card rounded animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-xs uppercase tracking-wider text-text-secondary font-medium mb-2">
        Timeline
        <span className="ml-2 text-text-muted normal-case tracking-normal">{data.total} events</span>
      </h2>
      {data.events.length === 0 ? (
        <p className="text-sm text-text-muted py-8 text-center">No status events recorded yet.</p>
      ) : (
        <div className="space-y-1">
          {data.events.map((event) => (
            <div key={event.id} className="bg-bg-card border border-border rounded px-3 py-2">
              <div className="flex items-center gap-2 text-sm">
                <StatusBadge status={event.new_status} />
                <span className="font-medium text-text-primary">{event.service_name}</span>
                <span className="text-text-muted">
                  {humanStatus(event.previous_status)}
                  <span className="mx-1">&rarr;</span>
                  <span style={{ color: `var(--color-status-${event.new_status === "partial_outage" ? "partial" : event.new_status === "major_outage" ? "major" : event.new_status})` }}>
                    {humanStatus(event.new_status)}
                  </span>
                </span>
                <span className="ml-auto text-xs text-text-muted shrink-0">
                  {timeAgo(event.created_at)}
                </span>
              </div>
              {event.impact_statement && (
                <p className="text-xs text-text-secondary mt-1 ml-5">{event.impact_statement}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
