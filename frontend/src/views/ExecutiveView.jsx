import { useExecutiveData } from "../hooks/use-executive-data";
import ExecutiveStatusPanel from "../components/executive/ExecutiveStatusPanel";
import ExecutiveKpiTiles from "../components/executive/ExecutiveKpiTiles";
import ExecutiveImpactList from "../components/executive/ExecutiveImpactList";

/** Top-level shell for the conference-room Executive view.
 *
 *  Phase 1 stacks the three primary surfaces — status panel, KPI tiles,
 *  impact list — vertically with generous whitespace. The 30-day trend
 *  strip lands in Phase 2 and slots between the tiles and the impact
 *  list; see docs/executive-view-redesign/IMPLEMENTATION-ROADMAP.md. */
export default function ExecutiveView() {
  const exec = useExecutiveData();
  return (
    <div className="space-y-10 pb-4" data-testid="executive-view">
      <ExecutiveStatusPanel exec={exec} />
      <ExecutiveKpiTiles exec={exec} />
      <ExecutiveImpactList exec={exec} />
    </div>
  );
}
