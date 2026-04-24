import { useState } from "react";
import { useSloData } from "../hooks/use-slo-data";
import SloGrid from "../components/slo/SloGrid";

/**
 * Top-level SLO snapshot view. Shows error-budget fuel gauges for all
 * monitored services, sorted by burn severity, with an aria-live region
 * that announces changes without spamming screen readers on every poll.
 */
export default function SloView() {
  const data = useSloData();

  // Derived-state-during-render: announce only on real burn-count transitions.
  // Same pattern as ExecutiveView — avoids setState-in-effect and aria-live spam.
  const [prevBurning, setPrevBurning] = useState(null);
  const [liveMessage, setLiveMessage] = useState("");
  if (prevBurning !== data.burningCount) {
    setPrevBurning(data.burningCount);
    setLiveMessage(
      data.burningCount === 0
        ? "All services within SLO budget"
        : `${data.burningCount} ${data.burningCount === 1 ? "service is" : "services are"} burning error budget`
    );
  }

  return (
    <section data-testid="slo-view" className="flex flex-col gap-8" aria-label="SLO snapshot">
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {liveMessage}
      </div>

      <header className="flex items-baseline justify-between">
        <h2 className="text-lede font-semibold text-text-display">
          Error budget across {data.services.length} services
        </h2>
        {data.burningCount > 0 && (
          <span className="text-body text-accent-alarm font-semibold">
            {data.burningCount} burning
          </span>
        )}
      </header>

      <SloGrid services={data.services} thresholds={data.thresholds} />
    </section>
  );
}
