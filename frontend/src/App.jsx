import { useState } from "react";
import { usePolling } from "./hooks/use-polling";
import { POLL_INTERVAL_MS } from "./lib/constants";
import SituationBanner from "./components/SituationBanner";
import MaintenanceBanner from "./components/MaintenanceBanner";
import StatusBoard from "./components/StatusBoard";
import Timeline from "./components/Timeline";
import ServiceDetail from "./components/ServiceDetail";
import LastUpdated from "./components/LastUpdated";

export default function App() {
  const [selectedServiceId, setSelectedServiceId] = useState(null);

  const summary = usePolling("/api/summary", POLL_INTERVAL_MS);
  const services = usePolling("/api/services", POLL_INTERVAL_MS);
  const timeline = usePolling("/api/timeline?limit=50", POLL_INTERVAL_MS);

  return (
    <div className="min-h-screen flex flex-col">
      <SituationBanner data={summary.data} loading={summary.loading} />
      <MaintenanceBanner data={summary.data} />

      <div className="flex-1 flex gap-4 p-4 pb-12 overflow-hidden">
        <div className="w-[60%] overflow-y-auto pr-2">
          <StatusBoard
            data={services.data}
            loading={services.loading}
            selectedId={selectedServiceId}
            onSelect={setSelectedServiceId}
          />
        </div>
        <div className="w-[40%] overflow-y-auto">
          <Timeline data={timeline.data} loading={timeline.loading} />
        </div>
      </div>

      <LastUpdated lastUpdated={summary.lastUpdated} />

      {selectedServiceId && (
        <ServiceDetail
          serviceId={selectedServiceId}
          onClose={() => setSelectedServiceId(null)}
        />
      )}
    </div>
  );
}
