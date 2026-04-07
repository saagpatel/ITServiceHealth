import { CATEGORY_ORDER, STATUS_COLORS, STATUS_ICONS } from "../lib/constants";
import StatusIndicator from "./StatusIndicator";

export default function CategorySummary({ services, slaData }) {
  if (!services?.services) {
    return (
      <div className="space-y-2">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-12 bg-bg-surface rounded-lg animate-pulse" />
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
    <div className="space-y-2">
      {CATEGORY_ORDER.map(({ key, label }) => {
        const svcs = servicesByCategory[key];
        if (!svcs || svcs.length === 0) return null;

        const issueCount = svcs.filter(
          (s) => s.current_status !== "operational" && s.current_status !== "unknown"
        ).length;

        const worstStatus = svcs.reduce((worst, s) => {
          const rank = { major_outage: 4, partial_outage: 3, degraded: 2, operational: 1, unknown: 0 };
          return (rank[s.current_status] || 0) > (rank[worst] || 0) ? s.current_status : worst;
        }, "operational");

        const healthyCount = svcs.filter((s) => s.current_status === "operational").length;

        // Category-level average SLA (7d)
        let avgSla = null;
        if (slaData?.services) {
          const slaValues = svcs
            .map((s) => slaData.services[s.id]?.uptime_7d)
            .filter((v) => v !== null && v !== undefined);
          if (slaValues.length > 0) {
            avgSla = slaValues.reduce((sum, v) => sum + v, 0) / slaValues.length;
          }
        }

        return (
          <div
            key={key}
            className="flex items-center justify-between bg-bg-surface rounded-lg px-4 py-3"
          >
            <div className="flex items-center gap-3">
              <StatusIndicator status={issueCount > 0 ? worstStatus : "operational"} size="sm" />
              <div>
                <span className="text-sm text-text-primary">{label}</span>
                <span className="text-xs text-text-muted ml-2">
                  {healthyCount}/{svcs.length} healthy
                </span>
              </div>
            </div>
            <div className="flex items-center gap-4">
              {avgSla !== null && (
                <span
                  className="text-xs font-medium"
                  style={{
                    color:
                      avgSla >= 99.9
                        ? STATUS_COLORS.operational
                        : avgSla >= 99
                          ? STATUS_COLORS.degraded
                          : STATUS_COLORS.major_outage,
                  }}
                >
                  {avgSla.toFixed(2)}%
                </span>
              )}
              {issueCount > 0 && (
                <span
                  className="text-xs font-medium"
                  style={{ color: STATUS_COLORS[worstStatus] }}
                >
                  {issueCount} issue{issueCount !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
