import { useState, useEffect, useMemo } from "react";
import { AlertTriangle, Network } from "lucide-react";
import { usePolling } from "./hooks/use-polling";
import {
  POLL_INTERVAL_MS,
  UPTIME_POLL_INTERVAL_MS,
  STALE_WARNING_MS,
  STALE_CRITICAL_MS,
} from "./lib/constants";
import StatusBanner from "./components/StatusBanner";
import IncidentSection from "./components/IncidentSection";
import MaintenanceBanner from "./components/MaintenanceBanner";
import ServiceGrid from "./components/ServiceGrid";
import Timeline from "./components/Timeline";
import ServiceDetail from "./components/ServiceDetail";
import DependencyGraph from "./components/DependencyGraph";
import ShortcutsOverlay from "./components/ShortcutsOverlay";

export default function App() {
  const [selectedServiceId, setSelectedServiceId] = useState(null);
  const [showGraph, setShowGraph] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [, setStaleTick] = useState(0);

  const summary = usePolling("/api/summary", POLL_INTERVAL_MS);
  const services = usePolling("/api/services", POLL_INTERVAL_MS);
  const timeline = usePolling("/api/timeline/clustered", POLL_INTERVAL_MS);
  const uptime = usePolling("/api/services/uptime", UPTIME_POLL_INTERVAL_MS);
  const sla = usePolling("/api/services/sla", UPTIME_POLL_INTERVAL_MS);

  useEffect(() => {
    const interval = setInterval(() => setStaleTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  // Global keyboard shortcuts
  useEffect(() => {
    const onKey = (e) => {
      // Ignore when typing into an input or when any modal is open
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.key === "?" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setShowShortcuts((s) => !s);
      } else if (e.key === "g" && !e.metaKey && !e.ctrlKey) {
        setShowGraph((s) => !s);
        e.preventDefault();
      } else if (e.key === "Escape") {
        if (selectedServiceId) setSelectedServiceId(null);
        else if (showGraph) setShowGraph(false);
        else if (showShortcuts) setShowShortcuts(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedServiceId, showGraph, showShortcuts]);

  // staleTick re-renders each second so this "now" reading stays fresh.
  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();
  const lastPollAge = summary.lastUpdated
    ? Math.floor((now - summary.lastUpdated) / 1000)
    : null;
  let staleClass = "text-text-muted";
  if (lastPollAge !== null && lastPollAge * 1000 > STALE_CRITICAL_MS)
    staleClass = "text-status-major";
  else if (lastPollAge !== null && lastPollAge * 1000 > STALE_WARNING_MS)
    staleClass = "text-status-degraded";

  // Any of our polled endpoints failing tells the user "the data you're
  // seeing might not be fresh" even when the backend itself is fine.
  const fetchErrors = [summary.error, services.error, timeline.error].filter(
    Boolean,
  );
  const hasFetchError = fetchErrors.length > 0;

  // Derive an aria-live summary of headline state so screen readers get
  // updates without being spammed per-tile. Only the high-level summary
  // is announced; individual tiles stay quiet.
  const liveSummary = useMemo(() => {
    if (!summary.data) return "";
    const { overall_status, active_incidents = [] } = summary.data;
    if (active_incidents.length > 0) {
      return `${active_incidents.length} active incident${
        active_incidents.length !== 1 ? "s" : ""
      }: overall status ${overall_status}.`;
    }
    return "All systems operational.";
  }, [summary.data]);

  return (
    <div className="min-h-screen bg-bg-page text-text-primary">
      {/* Screen-reader-only live region — announces headline state changes */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {liveSummary}
      </div>

      <div className="max-w-5xl mx-auto px-8 py-8 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Pulse</h1>
            <p className="text-xs text-text-muted mt-0.5">IT Service Health</p>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setShowGraph(true)}
              className="text-xs text-text-secondary hover:text-text-primary transition-colors cursor-pointer
                         flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-white/5"
              aria-label="Show dependency graph (g)"
            >
              <Network size={14} strokeWidth={2} />
              Dependencies
            </button>
            <button
              onClick={() => setShowShortcuts(true)}
              className="text-xs text-text-muted hover:text-text-primary transition-colors
                         px-2 py-1 rounded hover:bg-white/5 font-mono"
              aria-label="Show keyboard shortcuts"
              title="Keyboard shortcuts (?)"
            >
              ?
            </button>
            <span className={`text-xs ${staleClass}`} data-tabular="true">
              {lastPollAge !== null ? `Last polled ${lastPollAge}s ago` : "Connecting..."}
            </span>
          </div>
        </div>

        {/* Fetch-error banner — the app itself is talking to a broken backend */}
        {hasFetchError && (
          <div
            role="alert"
            className="rounded-lg bg-status-major/10 border border-status-major/40 px-4 py-3
                       flex items-start gap-3"
          >
            <AlertTriangle
              size={18}
              strokeWidth={2.5}
              className="text-status-major shrink-0 mt-0.5"
            />
            <div className="flex-1">
              <div className="text-sm font-medium text-status-major">
                Dashboard is having trouble reaching the backend
              </div>
              <div className="text-xs text-text-secondary mt-0.5">
                Data on this page may be stale. Automatically retrying every{" "}
                {POLL_INTERVAL_MS / 1000}s.
                {fetchErrors[0]?.message && (
                  <span className="block mt-1 font-mono opacity-75">
                    {fetchErrors[0].message}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Status Banner */}
        <StatusBanner data={summary.data} loading={summary.loading} />

        {/* Active Incidents */}
        <IncidentSection incidents={summary.data?.active_incidents} />

        {/* Service Grid */}
        <ServiceGrid
          services={services.data}
          slaData={sla.data}
          selectedId={selectedServiceId}
          onSelect={setSelectedServiceId}
        />

        {/* Maintenance */}
        <MaintenanceBanner data={summary.data} />

        {/* Timeline */}
        <Timeline data={timeline.data} loading={timeline.loading} />

        {/* Footer */}
        <div className="border-t border-border pt-4 pb-8 text-center">
          <span className="text-xs text-text-muted">
            Pulse v0.1.0
            {lastPollAge !== null && (
              <>
                {" "}
                · <span className={staleClass}>Last updated {lastPollAge}s ago</span>
              </>
            )}
          </span>
        </div>
      </div>

      {/* Dependency Graph Overlay */}
      {showGraph && (
        <DependencyGraph
          onSelectService={(id) => {
            setSelectedServiceId(id);
            setShowGraph(false);
          }}
          onClose={() => setShowGraph(false)}
        />
      )}

      {/* Service Detail Panel */}
      {selectedServiceId && (
        <ServiceDetail
          serviceId={selectedServiceId}
          uptimeData={uptime.data}
          slaData={sla.data}
          onClose={() => setSelectedServiceId(null)}
        />
      )}

      {/* Keyboard shortcuts overlay */}
      {showShortcuts && (
        <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />
      )}
    </div>
  );
}
