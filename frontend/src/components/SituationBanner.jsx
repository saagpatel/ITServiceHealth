export default function SituationBanner({ data, loading }) {
  if (loading || !data) {
    return <div className="h-12 bg-banner-healthy animate-pulse" />;
  }

  const { overall_status, active_incidents, status_text } = data;

  let bgClass = "bg-banner-healthy";
  if (overall_status === "major_outage") bgClass = "bg-banner-critical";
  else if (overall_status === "partial_outage") bgClass = "bg-banner-critical";
  else if (overall_status === "degraded") bgClass = "bg-banner-warning";

  return (
    <div className={`${bgClass} px-4 py-3`}>
      <div className="flex items-center gap-2">
        {overall_status === "operational" && (
          <svg className="w-4 h-4 text-status-operational" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
          </svg>
        )}
        <span className="text-sm font-medium text-text-primary">{status_text}</span>
      </div>
      {active_incidents && active_incidents.length > 0 && (
        <div className="mt-2 space-y-1">
          {active_incidents.map((incident) => (
            <div key={incident.service.id} className="text-xs text-text-secondary">
              <span className="font-medium text-text-primary">{incident.service.display_name}</span>
              {" — "}
              {incident.impact_statement}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
