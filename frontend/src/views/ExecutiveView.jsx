import { useState } from "react";
import { useExecutiveData } from "../hooks/use-executive-data";
import ExecutiveStatusPanel from "../components/executive/ExecutiveStatusPanel";
import ExecutiveKpiTiles from "../components/executive/ExecutiveKpiTiles";
import ExecutiveTrendStrip from "../components/executive/ExecutiveTrendStrip";
import ExecutiveImpactList from "../components/executive/ExecutiveImpactList";

export default function ExecutiveView() {
  const execData = useExecutiveData();

  // React 19 derived-state-during-render pattern — update the live-region
  // message only when overallStatus actually transitions. Avoids aria-live
  // spam from the 30-s poll tick while staying off the setState-in-effect
  // path. https://react.dev/reference/react/useState#storing-information-from-previous-renders
  const [prevStatus, setPrevStatus] = useState(null);
  const [liveMessage, setLiveMessage] = useState("");
  if (prevStatus !== execData.overallStatus) {
    setPrevStatus(execData.overallStatus);
    const slaPart =
      typeof execData.slaObserved === "number" && Number.isFinite(execData.slaObserved)
        ? `SLA ${execData.slaObserved.toFixed(2)} percent`
        : "SLA unavailable";
    setLiveMessage(
      `${execData.incidentsOpen} incidents open, ${execData.vendorsDegraded} vendors degraded, ${slaPart}`,
    );
  }

  return (
    <section
      className="grid grid-cols-12 gap-16"
      data-testid="executive-view"
      aria-label="Executive status summary"
    >
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {liveMessage}
      </div>
      <div className="col-span-12">
        <ExecutiveStatusPanel
          overallStatus={execData.overallStatus}
          headline={execData.headline}
          lastUpdatedMs={execData.lastUpdatedMs}
          isStale={execData.isStale}
        />
      </div>
      <div className="col-span-12">
        <ExecutiveKpiTiles
          incidentsOpen={execData.incidentsOpen}
          vendorsDegraded={execData.vendorsDegraded}
          slaObserved={execData.slaObserved}
          slaDeltaBps={execData.slaDeltaBps}
        />
      </div>
      <div className="col-span-12">
        <ExecutiveTrendStrip trend={execData.trend} />
      </div>
      <div className="col-span-12">
        <ExecutiveImpactList impact={execData.impact} />
      </div>
    </section>
  );
}
