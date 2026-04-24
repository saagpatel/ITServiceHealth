import SloFuelGauge from "./SloFuelGauge";

/**
 * Responsive grid of SloFuelGauge cards.
 *
 * @param {{ services: import("../../hooks/use-slo-data").SloService[], thresholds: Object|null }} props
 */
export default function SloGrid({ services, thresholds }) {
  if (!services || services.length === 0) {
    return (
      <div className="bg-surface-elev-1 rounded-lg px-10 py-12 text-center">
        <p className="text-lede text-text-dim">No services monitored</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
      {services.map(svc => (
        <SloFuelGauge key={svc.id} service={svc} thresholds={thresholds} />
      ))}
    </div>
  );
}
