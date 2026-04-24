import {
  EXEC_SLA_TARGET,
  formatSlaPct,
  formatDeltaBps,
} from "../../lib/executive-tokens";

/** Three KPI tiles: Incidents open · Vendors degraded · SLA 30 d vs target.
 *
 *  Numbers render at the h2 scale (56 px ideal, clamp-protected).
 *  The SLA delta uses `--color-accent-alarm` ONLY when observed is below
 *  target; positive and on-target deltas render in the dim text color.
 *  That single-accent discipline is what the redesign contract buys. */
export default function ExecutiveKpiTiles({ exec }) {
  const {
    incidentsOpen,
    vendorsDegraded,
    slaObserved,
    slaDeltaBps,
    loading,
  } = exec;

  const tiles = [
    {
      label: "Incidents open",
      value: loading ? "…" : String(incidentsOpen ?? 0),
      emphasize: (incidentsOpen ?? 0) > 0,
    },
    {
      label: "Vendors degraded",
      value: loading ? "…" : String(vendorsDegraded ?? 0),
      emphasize: (vendorsDegraded ?? 0) > 0,
    },
    {
      label: `SLA 30 d vs ${EXEC_SLA_TARGET.toFixed(2)}%`,
      value: loading ? "…" : formatSlaPct(slaObserved),
      delta:
        slaObserved === null || slaObserved === undefined
          ? null
          : formatDeltaBps(slaObserved),
      deltaNegative:
        slaDeltaBps !== null &&
        slaDeltaBps !== undefined &&
        slaDeltaBps < 0,
    },
  ];

  return (
    <section
      aria-label="Key performance indicators"
      // Stack one-per-row below 1024 px so 4:3 NOC screens and portrait
      // wall mounts never break the tile layout. Three equal columns
      // above the lg breakpoint, which is the 16:9 boardroom case.
      className="grid grid-cols-1 lg:grid-cols-3 gap-4"
    >
      {tiles.map((tile) => (
        <div
          key={tile.label}
          className="bg-surface-elev-1 border border-border rounded-2xl px-6 py-5 min-h-[9rem] flex flex-col justify-between"
        >
          <p className="text-exec-body text-text-dim">{tile.label}</p>
          <div className="flex items-end gap-3 mt-3">
            <span
              className={`${tile.emphasize ? "text-accent-alarm" : "text-text-display"} font-bold leading-none tracking-tight`}
              style={{ fontSize: "clamp(2.5rem, 5vw, 3.75rem)" }}
              data-tabular="true"
            >
              {tile.value}
            </span>
          </div>
          {tile.delta !== undefined && (
            <p
              className={`mt-3 text-exec-body font-mono ${tile.deltaNegative ? "text-accent-alarm" : "text-text-dim"}`}
              data-tabular="true"
            >
              {tile.delta ?? "—"}
            </p>
          )}
        </div>
      ))}
    </section>
  );
}
