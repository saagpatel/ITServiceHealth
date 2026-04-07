import { useState, useEffect } from "react";
import { usePolling } from "./hooks/use-polling";
import { POLL_INTERVAL_MS, UPTIME_POLL_INTERVAL_MS, STALE_WARNING_MS, STALE_CRITICAL_MS } from "./lib/constants";
import StatusBanner from "./components/StatusBanner";
import IncidentSection from "./components/IncidentSection";
import MaintenanceBanner from "./components/MaintenanceBanner";
import ServiceGrid from "./components/ServiceGrid";
import Timeline from "./components/Timeline";
import ServiceDetail from "./components/ServiceDetail";
import DependencyGraph from "./components/DependencyGraph";

export default function App() {
  const [selectedServiceId, setSelectedServiceId] = useState(null);
  const [showGraph, setShowGraph] = useState(false);
  const [staleTick, setStaleTick] = useState(0);

  const summary = usePolling("/api/summary", POLL_INTERVAL_MS);
  const services = usePolling("/api/services", POLL_INTERVAL_MS);
  const timeline = usePolling("/api/timeline/clustered", POLL_INTERVAL_MS);
  const uptime = usePolling("/api/services/uptime", UPTIME_POLL_INTERVAL_MS);
  const sla = usePolling("/api/services/sla", UPTIME_POLL_INTERVAL_MS);

  useEffect(() => {
    const interval = setInterval(() => setStaleTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  const lastPollAge = summary.lastUpdated ? Math.floor((Date.now() - summary.lastUpdated) / 1000) : null;
  let staleClass = "text-text-muted";
  if (lastPollAge !== null && lastPollAge * 1000 > STALE_CRITICAL_MS) staleClass = "text-status-major";
  else if (lastPollAge !== null && lastPollAge * 1000 > STALE_WARNING_MS) staleClass = "text-status-degraded";

  return (
    <div className="min-h-screen bg-bg-page text-text-primary">
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
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <circle cx="5" cy="12" r="2" strokeWidth="2" />
                <circle cx="19" cy="6" r="2" strokeWidth="2" />
                <circle cx="19" cy="18" r="2" strokeWidth="2" />
                <path strokeWidth="2" d="M7 11l10-4M7 13l10 4" />
              </svg>
              Dependencies
            </button>
            <span className={`text-xs ${staleClass}`}>
              {lastPollAge !== null ? `Last polled ${lastPollAge}s ago` : "Connecting..."}
            </span>
          </div>
        </div>

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
              <> · <span className={staleClass}>Last updated {lastPollAge}s ago</span></>
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
    </div>
  );
}
