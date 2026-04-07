import StatusIndicator from "./StatusIndicator";

export default function StatusBanner({ data, loading }) {
  if (loading || !data) {
    return (
      <div className="rounded-lg bg-banner-ok/50 px-5 py-4 animate-pulse">
        <div className="h-5 w-64 bg-bg-hover rounded" />
        <div className="h-3 w-40 bg-bg-hover rounded mt-2" />
      </div>
    );
  }

  const { overall_status, active_incidents, total_services = 0, healthy_count, unknown_count = 0 } = data;
  const hasIncidents = active_incidents && active_incidents.length > 0;
  const monitored = total_services - unknown_count;
  const manual = unknown_count;

  let bgClass = "bg-banner-ok";
  if (overall_status === "major_outage" || overall_status === "partial_outage") bgClass = "bg-banner-crit";
  else if (overall_status === "degraded") bgClass = "bg-banner-warn";

  return (
    <div className={`rounded-lg ${bgClass} px-5 py-4`}>
      <div className="flex items-center gap-2.5">
        <StatusIndicator status={hasIncidents ? overall_status : "operational"} size="md" />
        <span className="text-base font-semibold text-text-primary">
          {hasIncidents
            ? `${active_incidents.length} Active Incident${active_incidents.length !== 1 ? "s" : ""}`
            : "All Systems Operational"}
        </span>
      </div>
      <p className="text-xs text-text-muted mt-1.5 ml-6">
        {monitored} monitored · {manual} manual
      </p>
    </div>
  );
}
