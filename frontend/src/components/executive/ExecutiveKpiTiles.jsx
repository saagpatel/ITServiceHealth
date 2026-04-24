import { formatSlaPct, formatDeltaBps } from "../../lib/executive-tokens";

function Tile({ label, value, sub, subAlarm }) {
  return (
    <div className="bg-surface-elev-1 rounded-lg px-8 py-10 flex flex-col gap-3 min-w-0">
      <span className="text-body uppercase tracking-[0.12em] text-text-dim">
        {label}
      </span>
      <span
        className="text-h2 font-bold text-text-display leading-none"
        data-tabular="true"
      >
        {value}
      </span>
      {sub && (
        <span
          className={`text-body font-mono ${subAlarm ? "text-accent-alarm" : "text-text-dim"}`}
          data-tabular="true"
        >
          {sub}
        </span>
      )}
    </div>
  );
}

export default function ExecutiveKpiTiles({
  incidentsOpen,
  vendorsDegraded,
  slaObserved,
  slaDeltaBps,
}) {
  const hasDelta = typeof slaDeltaBps === "number" && Number.isFinite(slaDeltaBps);
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <Tile label="Incidents open" value={incidentsOpen} />
      <Tile label="Vendors degraded" value={vendorsDegraded} />
      <Tile
        label="SLA (30d) vs target"
        value={formatSlaPct(slaObserved)}
        sub={hasDelta ? formatDeltaBps(slaDeltaBps) : null}
        subAlarm={hasDelta && slaDeltaBps < 0}
      />
    </div>
  );
}
