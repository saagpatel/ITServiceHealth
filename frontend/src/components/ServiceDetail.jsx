import { useEffect } from "react";
import { usePolling } from "../hooks/use-polling";
import { POLL_INTERVAL_MS, SEVERITY_COLORS } from "../lib/constants";
import { timeAgo, humanStatus } from "../lib/format";
import StatusBadge from "./StatusBadge";

export default function ServiceDetail({ serviceId, onClose }) {
  const { data, loading } = usePolling(
    serviceId ? `/api/services/${serviceId}` : null,
    POLL_INTERVAL_MS
  );

  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />

      {/* Panel */}
      <div className="fixed top-0 right-0 h-full w-[480px] bg-bg-card border-l border-border z-50
                      overflow-y-auto shadow-2xl animate-slide-in">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 text-text-muted hover:text-text-primary cursor-pointer"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {loading || !data ? (
          <div className="p-6 space-y-4">
            <div className="h-6 w-48 bg-bg-hover rounded animate-pulse" />
            <div className="h-4 w-32 bg-bg-hover rounded animate-pulse" />
            <div className="h-20 bg-bg-hover rounded animate-pulse" />
          </div>
        ) : (
          <div className="p-6">
            {/* Header */}
            <div className="mb-6">
              <h2 className="text-lg font-semibold text-text-primary mb-1">
                {data.service.display_name}
              </h2>
              <StatusBadge status={data.service.current_status} showLabel size="md" />
              {data.service.current_status_detail && (
                <p className="text-xs text-text-secondary mt-2">{data.service.current_status_detail}</p>
              )}
            </div>

            {/* Vendor link */}
            {data.service.status_page_url && (
              <a
                href={data.service.status_page_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-accent hover:underline mb-6"
              >
                View vendor status page
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
            )}

            {/* Upstream dependencies */}
            <Section title="Depends On">
              {data.upstream_dependencies.length === 0 ? (
                <p className="text-xs text-text-muted">No upstream dependencies.</p>
              ) : (
                data.upstream_dependencies.map((dep) => (
                  <DepRow key={dep.service_id} dep={dep} />
                ))
              )}
            </Section>

            {/* Downstream impacts */}
            <Section title="Impacts">
              {data.downstream_impacts.length === 0 ? (
                <p className="text-xs text-text-muted">No downstream dependencies.</p>
              ) : (
                data.downstream_impacts.map((dep) => (
                  <DepRow key={dep.service_id} dep={dep} />
                ))
              )}
            </Section>

            {/* Recent events */}
            <Section title="Recent Events">
              {data.recent_events.length === 0 ? (
                <p className="text-xs text-text-muted">No events recorded.</p>
              ) : (
                data.recent_events.map((event) => (
                  <div key={event.id} className="py-1.5 border-b border-border last:border-0">
                    <div className="flex items-center gap-2 text-xs">
                      <StatusBadge status={event.new_status} />
                      <span className="text-text-muted">
                        {humanStatus(event.previous_status)} &rarr; {humanStatus(event.new_status)}
                      </span>
                      <span className="ml-auto text-text-muted">{timeAgo(event.created_at)}</span>
                    </div>
                    {event.vendor_title && (
                      <p className="text-xs text-text-secondary mt-0.5 ml-5">{event.vendor_title}</p>
                    )}
                  </div>
                ))
              )}
            </Section>
          </div>
        )}
      </div>
    </>
  );
}

function Section({ title, children }) {
  return (
    <div className="mb-5">
      <h3 className="text-xs uppercase tracking-wider text-text-secondary font-medium mb-2">{title}</h3>
      {children}
    </div>
  );
}

function DepRow({ dep }) {
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-border last:border-0">
      <StatusBadge status={dep.current_status} />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-text-primary">{dep.service_name}</span>
          <span
            className="text-xs font-medium"
            style={{ color: SEVERITY_COLORS[dep.severity] || SEVERITY_COLORS.low }}
          >
            {dep.severity}
          </span>
        </div>
        <p className="text-xs text-text-muted">{dep.impact_description}</p>
      </div>
    </div>
  );
}
