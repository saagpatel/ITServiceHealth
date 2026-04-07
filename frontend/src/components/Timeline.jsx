import { useState } from "react";
import StatusIndicator from "./StatusIndicator";
import { timeAgo, formatTimestamp, humanStatus } from "../lib/format";
import { STATUS_COLORS } from "../lib/constants";

export default function Timeline({ data, loading }) {
  if (loading || !data) {
    return (
      <div>
        <h2 className="text-[11px] uppercase tracking-wider text-text-secondary font-semibold px-3 py-2">
          Recent Events
        </h2>
        <div className="space-y-2 px-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-10 bg-bg-surface rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  const clusters = data.clusters || [];
  const totalEvents = data.total_events || 0;

  return (
    <div>
      <div className="flex items-center justify-between px-3 py-2">
        <h2 className="text-[11px] uppercase tracking-wider text-text-secondary font-semibold">
          Recent Events
        </h2>
        <span className="text-[11px] text-text-muted">
          {totalEvents} events · {clusters.length} cluster{clusters.length !== 1 ? "s" : ""}
        </span>
      </div>
      {clusters.length === 0 ? (
        <p className="text-xs text-text-muted px-3 py-6 text-center">No status events recorded.</p>
      ) : (
        <div className="border-t border-border">
          {clusters.map((cluster) => (
            <ClusterGroup key={cluster.started_at} cluster={cluster} />
          ))}
        </div>
      )}
    </div>
  );
}

function ClusterGroup({ cluster }) {
  const [expanded, setExpanded] = useState(false);
  const isSingle = cluster.event_count === 1;
  const events = cluster.events || [];
  const color = STATUS_COLORS[cluster.severity] || STATUS_COLORS.unknown;

  // Single-event clusters render inline (no expand)
  if (isSingle && events.length === 1) {
    return <EventRow event={events[0]} />;
  }

  return (
    <div className="border-b border-border last:border-b-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2.5 hover:bg-white/5 transition-colors cursor-pointer text-left"
      >
        <div className="flex items-center gap-2">
          <svg
            className={`w-3 h-3 text-text-muted transition-transform ${expanded ? "rotate-90" : ""}`}
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
          </svg>
          <StatusIndicator status={cluster.severity} size="sm" />
          <span className="text-sm font-medium text-text-primary">
            {cluster.service_count} service{cluster.service_count !== 1 ? "s" : ""} affected
          </span>
          {cluster.root_cause && (
            <span
              className="text-[10px] font-medium px-1.5 py-0.5 rounded"
              style={{ backgroundColor: color + "22", color }}
            >
              Root: {cluster.root_cause.name}
            </span>
          )}
          <span className="ml-auto text-xs text-text-muted shrink-0">
            {timeAgo(cluster.started_at)}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-1 ml-5">
          <span className="text-[11px] text-text-muted">
            {cluster.event_count} event{cluster.event_count !== 1 ? "s" : ""}
            {cluster.started_at !== cluster.ended_at && (
              <> · {formatTimestamp(cluster.started_at)} — {formatTimestamp(cluster.ended_at)}</>
            )}
          </span>
        </div>
      </button>
      {expanded && (
        <div className="bg-white/[0.02] border-t border-border">
          {events.map((event) => (
            <EventRow key={event.id} event={event} nested />
          ))}
        </div>
      )}
    </div>
  );
}

function EventRow({ event, nested = false }) {
  return (
    <div className={`px-3 py-2.5 border-b border-border last:border-b-0 hover:bg-white/5 transition-colors
                     ${nested ? "pl-8" : ""}`}>
      <div className="flex items-center gap-2">
        <StatusIndicator status={event.new_status} size="sm" />
        <span className="text-sm font-medium text-text-primary">{event.service_name}</span>
        <span className="text-xs text-text-muted">
          {humanStatus(event.previous_status)}
          <span className="mx-1">&rarr;</span>
          <span style={{ color: STATUS_COLORS[event.new_status] || STATUS_COLORS.unknown }}>
            {humanStatus(event.new_status)}
          </span>
        </span>
        <span className="ml-auto text-xs text-text-muted shrink-0">
          {timeAgo(event.created_at)}
        </span>
      </div>
      {event.impact_statement && (
        <p className="text-xs text-text-muted mt-1 ml-5 line-clamp-2 leading-relaxed">
          {event.impact_statement}
        </p>
      )}
    </div>
  );
}
