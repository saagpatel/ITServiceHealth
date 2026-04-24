import { CheckCircle2, AlertTriangle, AlertOctagon, HelpCircle } from "lucide-react";

const STATUS_META = {
  operational: { label: "Operational", Icon: CheckCircle2 },
  degraded: { label: "Degraded", Icon: AlertTriangle },
  partial_outage: { label: "Partial Outage", Icon: AlertTriangle },
  major_outage: { label: "Major Outage", Icon: AlertOctagon },
  unknown: { label: "Unknown", Icon: HelpCircle },
};

const ALARM_STATES = new Set(["degraded", "partial_outage", "major_outage"]);

function formatClock(ms) {
  if (typeof ms !== "number") return "—";
  const d = new Date(ms);
  return d.toLocaleTimeString(undefined, { hour12: false });
}

export default function ExecutiveStatusPanel({
  overallStatus,
  headline,
  lastUpdatedMs,
  isStale,
}) {
  const isAlarm = ALARM_STATES.has(overallStatus);
  const meta = STATUS_META[overallStatus] || STATUS_META.unknown;
  const Icon = meta.Icon;
  const bgClass = isAlarm ? "bg-accent-alarm" : "bg-surface-elev-1";

  return (
    <section
      className={`${bgClass} rounded-lg px-10 py-12 flex flex-col gap-6 min-h-[22rem] justify-between`}
    >
      <div>
        <span className="inline-flex items-center gap-2 rounded-full bg-black/25 px-3 py-1 text-body font-medium text-text-display">
          <Icon size={16} strokeWidth={2} aria-hidden="true" />
          {meta.label}
        </span>
      </div>

      <h2
        className="text-[clamp(4rem,12vw,7rem)] leading-[0.95] font-bold text-text-display text-balance"
      >
        {headline}
      </h2>

      <p
        className="text-body text-text-display/80 font-mono self-end"
        data-tabular="true"
      >
        {isStale ? "Stale · " : "Updated "}
        {formatClock(lastUpdatedMs)}
      </p>
    </section>
  );
}
