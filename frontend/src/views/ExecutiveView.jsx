import { useExecutiveData } from "../hooks/use-executive-data";

/** Top-level shell for the conference-room Executive view.
 *
 *  Phase 0 deliberately renders only a testid'd placeholder — the four
 *  regions (status panel · KPI tiles · trend strip · impact list) land
 *  in Phase 1 and Phase 2 per
 *  docs/executive-view-redesign/IMPLEMENTATION-ROADMAP.md. The shell
 *  exercises the data hook end-to-end so the wire-up is verifiable
 *  before any UI is built on top of it. */
export default function ExecutiveView() {
  const exec = useExecutiveData();
  // The sentinel alarm-border below exercises the Phase 0 --color-accent-alarm
  // token end-to-end so Tailwind emits it into the built CSS. It will be
  // replaced by real usage when Phase 1 lands ExecutiveStatusPanel.
  const hasIncident = exec.incidentsOpen > 0;
  return (
    <div
      data-testid="exec-shell"
      className={`space-y-2 py-4 pl-3 border-l-2 ${
        hasIncident ? "border-accent-alarm" : "border-border"
      }`}
    >
      <p className="text-sm text-text-display font-mono">exec shell ready</p>
      <p className="text-xs text-text-dim font-mono">
        {exec.loading
          ? "loading…"
          : `${exec.headline} · ${exec.incidentsOpen} open · ${exec.vendorsDegraded} degraded · ${exec.trend.length} trend points`}
      </p>
    </div>
  );
}
