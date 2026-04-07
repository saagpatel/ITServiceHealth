import { CATEGORY_ORDER } from "../lib/constants";
import ServiceCard from "./ServiceCard";

export default function StatusBoard({ data, loading, selectedId, onSelect }) {
  if (loading || !data) {
    return (
      <div className="space-y-4">
        {[...Array(5)].map((_, i) => (
          <div key={i}>
            <div className="h-3 w-32 bg-bg-hover rounded animate-pulse mb-2" />
            <div className="grid grid-cols-3 gap-1.5">
              {[...Array(3)].map((_, j) => (
                <div key={j} className="h-9 bg-bg-card rounded animate-pulse" />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  const servicesByCategory = {};
  for (const svc of data.services) {
    if (!servicesByCategory[svc.category]) {
      servicesByCategory[svc.category] = [];
    }
    servicesByCategory[svc.category].push(svc);
  }

  return (
    <div className="space-y-4">
      {CATEGORY_ORDER.map(({ key, label }) => {
        const services = servicesByCategory[key];
        if (!services || services.length === 0) return null;
        return (
          <div key={key}>
            <h3 className="text-xs uppercase tracking-wider text-text-secondary mb-1.5 font-medium">
              {label}
            </h3>
            <div className="grid grid-cols-3 gap-1.5">
              {services.map((svc) => (
                <ServiceCard
                  key={svc.id}
                  service={svc}
                  isSelected={selectedId === svc.id}
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
