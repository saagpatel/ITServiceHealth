import { STATUS_LABELS } from "../../lib/constants";
import { EXEC_IMPACT_LIMIT } from "../../lib/executive-tokens";

/** Format an ISO timestamp as a short "since" duration — 24 m, 2 h, 3 d.
 *  Falls back to an em-dash when the timestamp is missing or unparseable. */
function formatSince(iso) {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const delta = Date.now() - t;
  if (delta < 0) return "just now";
  const minutes = Math.floor(delta / 60_000);
  if (minutes < 60) return `${minutes} m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h`;
  const days = Math.floor(hours / 24);
  return `${days} d`;
}

/** Sorted impact list — worst status first, capped at EXEC_IMPACT_LIMIT.
 *
 *  Rows use an alarm-red left bar instead of a background fill so the
 *  status panel above keeps its role as the single eye-magnet. Status
 *  chip on the right is alarm-red for degraded/major/partial, muted for
 *  unknown (poller-broken state), which distinguishes "the vendor told
 *  us they're in trouble" from "we can't reach the vendor". */
export default function ExecutiveImpactList({ exec }) {
  const { impact, loading } = exec;
  const affected = impact?.length ?? 0;
  const total = exec.totalMonitored + (exec.vendorsDegraded ?? 0);

  return (
    <section aria-label="Active impact" className="bg-surface-elev-1 border border-border rounded-2xl">
      <header className="flex items-center justify-between px-6 pt-5 pb-3">
        <h3 className="text-exec-body text-text-dim">Active impact</h3>
        <span className="text-exec-body font-mono text-text-dim" data-tabular="true">
          {affected === 0 ? "0 affected" : `${affected} of ${total || 30} affected`}
        </span>
      </header>

      {loading ? (
        <div className="px-6 pb-6 pt-4">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-16 bg-surface-elev-2 rounded-lg animate-pulse mb-2"
            />
          ))}
        </div>
      ) : affected === 0 ? (
        <div className="px-6 pb-10 pt-8 text-center">
          <p className="text-exec-lede text-text-dim">No active impact</p>
        </div>
      ) : (
        <ul className="divide-y divide-border" role="list">
          {impact.slice(0, EXEC_IMPACT_LIMIT).map((row) => {
            const chipClass =
              row.status === "unknown"
                ? "bg-surface-elev-2 text-text-dim"
                : "bg-accent-alarm text-white";
            return (
              <li
                key={row.id}
                tabIndex={0}
                className="flex items-stretch gap-4 px-6 py-4 focus:outline-none focus-visible:bg-surface-elev-2"
                aria-label={`${row.label} · ${STATUS_LABELS[row.status] ?? row.status} · ${row.impactLine}`}
              >
                <span
                  aria-hidden="true"
                  className="w-1 rounded-full bg-accent-alarm shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <span className="text-exec-lede font-semibold text-text-display leading-tight">
                      {row.label}
                    </span>
                    <span
                      className={`${chipClass} text-[0.65rem] tracking-wider uppercase font-bold px-2 py-0.5 rounded-md font-mono`}
                    >
                      {STATUS_LABELS[row.status] ?? row.status}
                    </span>
                  </div>
                  <p className="mt-1 text-exec-body text-text-secondary">
                    {row.impactLine}
                  </p>
                </div>
                <span
                  className="text-exec-body text-text-secondary font-mono shrink-0 self-center"
                  data-tabular="true"
                >
                  {formatSince(row.sinceIso)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
