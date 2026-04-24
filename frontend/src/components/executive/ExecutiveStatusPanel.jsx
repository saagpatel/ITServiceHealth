import {
  STATUS_ICON_COMPONENTS,
  STATUS_LABELS,
} from "../../lib/constants";

/** Full-width primary status panel for the Executive view.
 *
 *  Visual rules (locked in the handoff CLAUDE.md):
 *    - Background is `--color-accent-alarm` ONLY when overall status is
 *      degraded, partial_outage, or major_outage. Everything else is
 *      `--color-surface-elev-1`. One eye-magnet per screen.
 *    - Headline renders at the display scale — clamp() protects narrow
 *      viewports so the 112 px ideal degrades gracefully to ~72 px on
 *      1280-wide monitors without wrapping oddly.
 *    - A monospace "last polled" timestamp sits bottom-right. */
export default function ExecutiveStatusPanel({ exec }) {
  const {
    overallStatus,
    headline,
    incidentsOpen,
    vendorsDegraded,
    totalMonitored,
    lastUpdatedMs,
    isStale,
    loading,
  } = exec;

  const isIncident =
    overallStatus === "degraded" ||
    overallStatus === "partial_outage" ||
    overallStatus === "major_outage";

  const panelBg = isIncident ? "bg-accent-alarm" : "bg-surface-elev-1";
  const headingColor = isIncident ? "text-white" : "text-text-display";
  const subColor = isIncident ? "text-red-100" : "text-text-dim";
  const dotColor = isIncident ? "bg-white" : "bg-status-operational";

  const Icon = STATUS_ICON_COMPONENTS[overallStatus] || null;

  // Subhead content mirrors the mockup — service-name run-on for incident
  // state, monitored/degraded count for the green state.
  let subhead;
  if (loading) {
    subhead = "Loading…";
  } else if (isIncident) {
    const parts = [];
    if (incidentsOpen > 0) {
      parts.push(
        `${incidentsOpen} open incident${incidentsOpen !== 1 ? "s" : ""}`,
      );
    }
    if (vendorsDegraded > 0) {
      parts.push(
        `${vendorsDegraded} vendor${vendorsDegraded !== 1 ? "s" : ""} degraded`,
      );
    }
    subhead = parts.join(" · ");
  } else {
    subhead = `${totalMonitored} monitored · ${STATUS_LABELS[overallStatus] ?? "Operational"}`;
  }

  // App.jsx's 1-Hz stale tick drives re-renders, so Date.now() here
  // yields a fresh timestamp each tick without its own timer. Mirrors
  // the precedent in App.jsx at line 71 where the same rule is disabled.
  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();
  const stamp = lastUpdatedMs
    ? `Last polled ${Math.round((now - lastUpdatedMs) / 1000)} s ago`
    : "Connecting…";

  return (
    <section
      aria-label="Overall service health"
      className={`${panelBg} rounded-2xl px-8 py-8 min-h-[15rem] flex flex-col justify-between`}
    >
      <div className="flex items-start gap-5">
        <span
          aria-hidden="true"
          className={`${dotColor} mt-6 inline-block h-4 w-4 rounded-full shrink-0`}
        />
        <div className="flex-1 min-w-0">
          <h2
            className={`${headingColor} font-bold leading-[0.95] tracking-tight`}
            style={{ fontSize: "clamp(3.5rem, 8vw, 7rem)" }}
          >
            {loading ? "…" : headline}
          </h2>
          <p className={`${subColor} mt-4 text-exec-lede`}>
            {subhead}
          </p>
        </div>
        {Icon && !isIncident && (
          <Icon
            size={56}
            strokeWidth={1.5}
            className="text-status-operational hidden lg:block shrink-0 mt-2"
            aria-hidden="true"
          />
        )}
      </div>

      <div
        className={`${subColor} mt-6 flex items-center justify-between font-mono text-exec-body`}
        data-tabular="true"
      >
        <span>Pulse · Executive</span>
        <span className={isStale ? "text-status-major" : ""}>
          {stamp}
        </span>
      </div>
    </section>
  );
}
