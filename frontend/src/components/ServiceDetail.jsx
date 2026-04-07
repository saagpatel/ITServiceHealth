import { useEffect } from "react";
import { usePolling } from "../hooks/use-polling";
import { POLL_INTERVAL_MS, UPTIME_POLL_INTERVAL_MS, SEVERITY_COLORS, STATUS_COLORS } from "../lib/constants";
import { timeAgo, formatTimestamp, humanStatus } from "../lib/format";
import StatusIndicator from "./StatusIndicator";
import UptimeBar from "./UptimeBar";

export default function ServiceDetail({ serviceId, uptimeData, slaData, onClose }) {
  const { data, loading } = usePolling(
    serviceId ? `/api/services/${serviceId}` : null,
    POLL_INTERVAL_MS
  );

  const reports = usePolling(
    serviceId ? `/api/reports?service_id=${serviceId}` : null,
    UPTIME_POLL_INTERVAL_MS
  );

  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  const uptimeDays = uptimeData?.days || [];
  const serviceUptime = uptimeData?.services?.[serviceId] || {};
  const serviceSla = slaData?.services?.[serviceId] || null;
  const reportList = reports.data?.reports || [];

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} role="button" aria-label="Close panel" tabIndex={-1} />
      <div className="fixed top-0 right-0 h-full w-full sm:w-[480px] bg-bg-page border-l border-border z-50
                      overflow-y-auto shadow-2xl animate-slide-in">
        <button
          onClick={onClose}
          aria-label="Close details panel"
          className="absolute top-4 right-4 text-text-muted hover:text-text-primary cursor-pointer"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {loading || !data ? (
          <div className="p-6 space-y-4">
            <div className="h-6 w-48 bg-bg-surface rounded animate-pulse" />
            <div className="h-4 w-32 bg-bg-surface rounded animate-pulse" />
          </div>
        ) : (
          <div className="p-6">
            <div className="mb-6">
              <h2 className="text-lg font-semibold text-text-primary mb-2">
                {data.service.display_name}
              </h2>
              <StatusIndicator status={data.service.current_status} showLabel size="md" />
              {data.service.current_status_detail && (
                <p className="text-xs text-text-secondary mt-2">{data.service.current_status_detail}</p>
              )}
              <div className="mt-3">
                <p className="text-[11px] uppercase tracking-wider text-text-muted mb-1">7-Day History</p>
                <UptimeBar days={uptimeDays} serviceUptime={serviceUptime} />
              </div>
            </div>

            {/* SLA / Uptime Percentages */}
            {serviceSla && (
              <Section title="Uptime SLA">
                <div className="grid grid-cols-3 gap-3">
                  <SlaCard label="24h" value={serviceSla.uptime_24h} />
                  <SlaCard label="7d" value={serviceSla.uptime_7d} />
                  <SlaCard label="30d" value={serviceSla.uptime_30d} />
                </div>
              </Section>
            )}

            {data.service.status_page_url && (
              <a
                href={data.service.status_page_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline mb-6"
              >
                View vendor status page
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
            )}

            <Section title="Depends On">
              {data.upstream_dependencies.length === 0 ? (
                <p className="text-xs text-text-muted">No upstream dependencies.</p>
              ) : (
                data.upstream_dependencies.map((dep) => <DepRow key={dep.service_id} dep={dep} />)
              )}
            </Section>

            <Section title="Impacts When Down">
              {data.downstream_impacts.length === 0 ? (
                <p className="text-xs text-text-muted">No downstream dependencies.</p>
              ) : (
                data.downstream_impacts.map((dep) => <DepRow key={dep.service_id} dep={dep} />)
              )}
            </Section>

            <Section title="Recent Events">
              {data.recent_events.length === 0 ? (
                <p className="text-xs text-text-muted">No events recorded.</p>
              ) : (
                data.recent_events.map((event) => (
                  <div key={event.id} className="py-2 border-b border-border last:border-0">
                    <div className="flex items-center gap-2 text-xs">
                      <StatusIndicator status={event.new_status} size="sm" />
                      <span className="text-text-secondary">
                        {humanStatus(event.previous_status)} &rarr; {humanStatus(event.new_status)}
                      </span>
                      <span className="ml-auto text-text-muted">{timeAgo(event.created_at)}</span>
                    </div>
                    {event.vendor_title && (
                      <p className="text-xs text-text-muted mt-0.5 ml-5">{event.vendor_title}</p>
                    )}
                  </div>
                ))
              )}
            </Section>

            {/* Incident Reports */}
            {reportList.length > 0 && (
              <Section title="Incident Reports">
                {reportList.map((report) => (
                  <ReportCard key={report.id} report={report} />
                ))}
              </Section>
            )}
          </div>
        )}
      </div>
    </>
  );
}

function SlaCard({ label, value }) {
  let color = "#64748b";
  let display = "—";
  if (value !== null && value !== undefined) {
    display = `${value.toFixed(2)}%`;
    if (value >= 99.9) color = STATUS_COLORS.operational;
    else if (value >= 99) color = STATUS_COLORS.degraded;
    else color = STATUS_COLORS.major_outage;
  }

  return (
    <div className="bg-bg-surface rounded-lg px-3 py-2.5 text-center">
      <div className="text-[11px] uppercase tracking-wider text-text-muted mb-1">{label}</div>
      <div className="text-lg font-semibold" style={{ color }}>{display}</div>
    </div>
  );
}

function ReportCard({ report }) {
  const color = STATUS_COLORS[report.peak_severity] || STATUS_COLORS.unknown;
  const downstream = report.affected_downstream || [];

  return (
    <div className="py-3 border-b border-border last:border-0">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <StatusIndicator status={report.peak_severity} size="sm" />
          <span className="text-xs font-medium" style={{ color }}>
            {humanStatus(report.peak_severity)}
          </span>
        </div>
        <span className="text-[11px] text-text-muted">{report.duration_human}</span>
      </div>
      <div className="text-[11px] text-text-muted mb-1.5">
        {formatTimestamp(report.started_at)} — {formatTimestamp(report.resolved_at)}
      </div>
      {report.impact_summary && (
        <p className="text-xs text-text-secondary leading-relaxed mb-1.5">{report.impact_summary}</p>
      )}
      {downstream.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {downstream.map((name) => (
            <span key={name} className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-text-muted">
              {name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="mb-5">
      <h3 className="text-[11px] uppercase tracking-wider text-text-secondary font-semibold mb-2">{title}</h3>
      {children}
    </div>
  );
}

function DepRow({ dep }) {
  return (
    <div className="flex items-start gap-2 py-2 border-b border-border last:border-0">
      <StatusIndicator status={dep.current_status} size="sm" />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-text-primary">{dep.service_name}</span>
          <span className="text-[11px] font-medium" style={{ color: SEVERITY_COLORS[dep.severity] || SEVERITY_COLORS.low }}>
            {dep.severity}
          </span>
        </div>
        <p className="text-xs text-text-muted">{dep.impact_description}</p>
      </div>
    </div>
  );
}
