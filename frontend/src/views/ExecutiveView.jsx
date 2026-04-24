import { useExecutiveData } from "../hooks/use-executive-data";
import ExecutiveStatusPanel from "../components/executive/ExecutiveStatusPanel";
import ExecutiveKpiTiles from "../components/executive/ExecutiveKpiTiles";
import ExecutiveTrendStrip from "../components/executive/ExecutiveTrendStrip";
import ExecutiveImpactList from "../components/executive/ExecutiveImpactList";

/** Top-level shell for the conference-room Executive view.
 *
 *  Four regions stacked vertically: status panel, KPI tiles, 30-day
 *  trend strip, sorted impact list. The `space-y-10` (2.5 rem = 40 px)
 *  plus the rounded-2xl padding on each surface lands the implied gap
 *  in the ≥ 64 px range the roadmap specifies. */
export default function ExecutiveView() {
  const exec = useExecutiveData();
  return (
    <div className="space-y-10 pb-4" data-testid="executive-view">
      <ExecutiveStatusPanel exec={exec} />
      <ExecutiveKpiTiles exec={exec} />
      <ExecutiveTrendStrip exec={exec} />
      <ExecutiveImpactList exec={exec} />
    </div>
  );
}
