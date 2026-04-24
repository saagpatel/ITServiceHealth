import { formatDistanceToNowStrict } from "date-fns";

// One-accent rule (scoped CLAUDE.md): every non-operational severity surfaces
// the same alarm red. Unknown stays neutral so a broken poller doesn't scream
// for attention.
const STATUS_CHIP = {
  degraded: "bg-accent-alarm/20 text-accent-alarm",
  partial_outage: "bg-accent-alarm/20 text-accent-alarm",
  major_outage: "bg-accent-alarm/20 text-accent-alarm",
  unknown: "bg-surface-elev-2 text-text-dim",
};

const STATUS_LABEL = {
  degraded: "Degraded",
  partial_outage: "Partial Outage",
  major_outage: "Major Outage",
  unknown: "Unknown",
};

function Since({ iso }) {
  if (!iso) {
    return (
      <span className="text-body text-text-dim font-mono" data-tabular="true">
        —
      </span>
    );
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return (
      <span className="text-body text-text-dim font-mono" data-tabular="true">
        —
      </span>
    );
  }
  return (
    <span
      className="text-body text-text-dim font-mono"
      data-tabular="true"
      title={iso}
    >
      {formatDistanceToNowStrict(d, { addSuffix: true })}
    </span>
  );
}

export default function ExecutiveImpactList({ impact }) {
  if (!impact || impact.length === 0) {
    return (
      <div className="bg-surface-elev-1 rounded-lg px-10 py-12 text-center">
        <p className="text-lede text-text-dim">No active impact</p>
      </div>
    );
  }

  return (
    <ul className="bg-surface-elev-1 rounded-lg divide-y divide-white/5">
      {impact.map((row) => {
        const chipClass = STATUS_CHIP[row.status] || STATUS_CHIP.unknown;
        const chipLabel = STATUS_LABEL[row.status] || row.status;
        return (
          <li
            key={row.id}
            className="px-8 py-6 flex items-start justify-between gap-6"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-lede font-semibold text-text-display truncate">
                  {row.label}
                </span>
                <span className={`text-body px-2.5 py-0.5 rounded-full ${chipClass}`}>
                  {chipLabel}
                </span>
                {row.isPollerBroken && (
                  <span className="text-body text-text-dim font-mono">
                    · poller down
                  </span>
                )}
              </div>
              <p className="text-body text-text-dim">{row.impactLine}</p>
            </div>
            <div className="flex-shrink-0 pt-1">
              <Since iso={row.sinceIso} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
