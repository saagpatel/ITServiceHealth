import { useExecutiveData } from "../hooks/use-executive-data";
import ExecutiveStatusPanel from "../components/executive/ExecutiveStatusPanel";
import ExecutiveKpiTiles from "../components/executive/ExecutiveKpiTiles";
import ExecutiveTrendStrip from "../components/executive/ExecutiveTrendStrip";
import ExecutiveImpactList from "../components/executive/ExecutiveImpactList";

export default function ExecutiveView() {
  const execData = useExecutiveData();
  return (
    <section
      className="grid grid-cols-12 gap-16"
      data-testid="executive-view"
    >
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
