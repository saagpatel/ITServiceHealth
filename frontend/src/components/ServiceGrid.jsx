import { CATEGORY_ORDER, STATUS_COLORS, STATUS_ICONS } from "../lib/constants";
import ServiceTile from "./ServiceTile";

export default function ServiceGrid({ services, slaData, selectedId, onSelect }) {
  if (!services?.services) {
    return (
      <div className="space-y-6">
        {[...Array(4)].map((_, i) => (
          <div key={i}>
            <div className="h-3 w-36 bg-bg-surface rounded animate-pulse mb-3" />
            <div className="grid grid-cols-4 gap-2">
              {[...Array(4)].map((_, j) => (
                <div key={j} className="h-[72px] bg-bg-surface rounded-lg animate-pulse" />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  const servicesByCategory = {};
  for (const svc of services.services) {
    if (!servicesByCategory[svc.category]) {
      servicesByCategory[svc.category] = [];
    }
    servicesByCategory[svc.category].push(svc);
  }

  return (
    <div className="space-y-5">
      {CATEGORY_ORDER.map(({ key, label }) => {
        const svcs = servicesByCategory[key];
        if (!svcs || svcs.length === 0) return null;

        // Sort: non-operational first (not unknown), then operational, then manual/unknown last
        const sorted = [...svcs].sort((a, b) => {
          const aManual = a.poll_type === "manual" && a.current_status === "unknown";
          const bManual = b.poll_type === "manual" && b.current_status === "unknown";
          if (aManual !== bManual) return aManual ? 1 : -1;

          const aOk = a.current_status === "operational" || a.current_status === "unknown";
          const bOk = b.current_status === "operational" || b.current_status === "unknown";
          if (aOk !== bOk) return aOk ? 1 : -1;

          return a.display_name.localeCompare(b.display_name);
        });

        // Category rollup: worst status
        const degradedCount = svcs.filter(
          (s) => s.current_status !== "operational" && s.current_status !== "unknown"
        ).length;

        const worstStatus = svcs.reduce((worst, s) => {
          const rank = { major_outage: 4, partial_outage: 3, degraded: 2, operational: 1, unknown: 0 };
          return (rank[s.current_status] || 0) > (rank[worst] || 0) ? s.current_status : worst;
        }, "operational");

        const rollupIcon = degradedCount > 0 ? STATUS_ICONS[worstStatus] : "✓";
        const rollupColor = degradedCount > 0 ? STATUS_COLORS[worstStatus] : STATUS_COLORS.operational;
        const rollupText = degradedCount > 0 ? `${degradedCount} issue${degradedCount !== 1 ? "s" : ""}` : "all ok";

        return (
          <div key={key}>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-[11px] uppercase tracking-wider text-text-secondary font-semibold">
                {label}
              </h3>
              <span className="text-[11px] flex items-center gap-1" style={{ color: rollupColor }}>
                <span>{rollupIcon}</span> {rollupText}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {sorted.map((svc) => (
                <ServiceTile
                  key={svc.id}
                  service={svc}
                  uptimePercent={slaData?.services?.[svc.id]?.uptime_7d ?? null}
                  onClick={onSelect}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
