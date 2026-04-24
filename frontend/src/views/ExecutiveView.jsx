import { useEffect, useMemo, useRef } from "react";
import { useExecutiveData } from "../hooks/use-executive-data";
import ExecutiveStatusPanel from "../components/executive/ExecutiveStatusPanel";
import ExecutiveKpiTiles from "../components/executive/ExecutiveKpiTiles";
import ExecutiveTrendStrip from "../components/executive/ExecutiveTrendStrip";
import ExecutiveImpactList from "../components/executive/ExecutiveImpactList";
import { formatSlaPct } from "../lib/executive-tokens";

/** Top-level shell for the conference-room Executive view.
 *
 *  Four regions stacked vertically: status panel, KPI tiles, 30-day
 *  trend strip, sorted impact list. The `space-y-10` (2.5 rem = 40 px)
 *  plus the rounded-2xl padding on each surface lands the implied gap
 *  in the ≥ 64 px range the roadmap specifies. */
export default function ExecutiveView() {
  const exec = useExecutiveData();
  const {
    overallStatus,
    incidentsOpen,
    vendorsDegraded,
    slaObserved,
  } = exec;

  // aria-live announcement for status transitions. Only fires when
  // overallStatus actually changes — equality-check via a ref prevents
  // the 30 s poll from spamming the screen reader even when nothing has
  // moved. Reads the three numbers a director actually asks for.
  //
  // The effect writes to state because the DOM text inside the aria-live
  // region must persist across renders — a ref alone would lose the
  // latest announcement on re-render. The rule's concern about cascading
  // renders doesn't apply: the transition set happens at most once per
  // real status flip (roughly minutes apart), not every poll.
  const lastStatusRef = useRef(null);
  const liveRef = useRef(null);
  useEffect(() => {
    if (lastStatusRef.current === overallStatus) return;
    if (lastStatusRef.current === null) {
      // First real status — silent prime so the reader isn't announced on load
      lastStatusRef.current = overallStatus;
      return;
    }
    lastStatusRef.current = overallStatus;
    // Write directly to the DOM instead of through React state: the
    // aria-live region is a side-effect target (the screen reader),
    // not part of the component's visual rendering. Bypassing state
    // also satisfies react-hooks/set-state-in-effect without a
    // per-site suppression.
    if (liveRef.current) {
      const sla = formatSlaPct(slaObserved);
      liveRef.current.textContent =
        `${incidentsOpen} incident${incidentsOpen === 1 ? "" : "s"} open, ` +
        `${vendorsDegraded} vendor${vendorsDegraded === 1 ? "" : "s"} degraded, ` +
        `SLA ${sla}`;
    }
  }, [overallStatus, incidentsOpen, vendorsDegraded, slaObserved]);

  // Memoize the rendered children so the aria-live state bump doesn't
  // force every panel to recompute on a screen-reader-only change.
  const children = useMemo(
    () => (
      <>
        <ExecutiveStatusPanel exec={exec} />
        <ExecutiveKpiTiles exec={exec} />
        <ExecutiveTrendStrip exec={exec} />
        <ExecutiveImpactList exec={exec} />
      </>
    ),
    [exec],
  );

  return (
    <div className="space-y-10 pb-4" data-testid="executive-view">
      {/* Screen-reader-only announcement for real status transitions.
          Polite so it doesn't interrupt an operator mid-sentence. The
          effect above writes textContent directly via liveRef — that's
          why there's no body in this element. */}
      <div
        ref={liveRef}
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      />

      {children}
    </div>
  );
}
