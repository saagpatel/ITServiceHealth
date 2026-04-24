import {
  RadialBarChart,
  RadialBar,
  PolarAngleAxis,
} from "recharts";
import { EXEC_CHART_COLORS } from "../../lib/executive-tokens";
import { pickZone, formatBudgetPct, formatBurnRate } from "../../lib/slo-tokens";

/**
 * Single SLO fuel-gauge card for one service.
 *
 * @param {{ service: import("../../hooks/use-slo-data").SloService, thresholds: Object|null }} props
 */
// eslint-disable-next-line no-unused-vars
export default function SloFuelGauge({ service, thresholds }) {
  const budget = service.error_budget_remaining_pct ?? 0;
  const zone = pickZone(budget, service.fast_burning);

  const chartData = [{ value: budget, fill: zone.color }];

  let burnFooter;
  if (service.fast_breach) {
    const rate = formatBurnRate(service.fast_breach.long_window_burn_rate);
    burnFooter = (
      <span className="text-accent-alarm">
        Burning {rate} over {service.fast_breach.long_window_label}
      </span>
    );
  } else if (service.slow_breach) {
    const rate = formatBurnRate(service.slow_breach.long_window_burn_rate);
    burnFooter = (
      <span className="text-status-degraded">
        Burning {rate} over {service.slow_breach.long_window_label}
      </span>
    );
  } else {
    burnFooter = (
      <span className="text-text-dim">Within budget</span>
    );
  }

  const borderClass = service.fast_burning
    ? "border border-accent-alarm"
    : "border border-white/5";

  return (
    <article
      className={`bg-surface-elev-1 rounded-lg p-6 flex flex-col gap-4 relative ${borderClass}`}
    >
      <header>
        <h3 className="text-lede font-semibold text-text-display truncate">
          {service.display_name}
        </h3>
        <p className="text-body text-text-dim capitalize">{service.category}</p>
      </header>

      <div className="relative flex items-center justify-center h-48">
        {/* Fixed-size chart — recharts' ResponsiveContainer measures 0x0 inside
            flex + absolute-overlay layouts at initial mount. 192px matches h-48. */}
        <RadialBarChart
          width={192}
          height={192}
          cx="50%"
          cy="50%"
          innerRadius="60%"
          outerRadius="85%"
          barSize={14}
          data={chartData}
          startAngle={225}
          endAngle={-45}
        >
          <PolarAngleAxis
            type="number"
            domain={[0, 100]}
            angleAxisId={0}
            tick={false}
          />
          <RadialBar
            dataKey="value"
            cornerRadius={8}
            background={{ fill: EXEC_CHART_COLORS.surfaceElev2 }}
            isAnimationActive={false}
          />
        </RadialBarChart>

        {/* Center number overlay */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-h2 font-bold text-text-display leading-none" data-tabular="true">
            {formatBudgetPct(budget)}
          </span>
          <span className="text-body text-text-dim">error budget</span>
        </div>
      </div>

      <footer className="text-body font-mono" data-tabular="true">
        {burnFooter}
      </footer>

      {service.fast_burning && (
        <span className="absolute top-4 right-4 bg-accent-alarm/25 text-accent-alarm text-body px-2 py-0.5 rounded-full font-semibold">
          Burning fast
        </span>
      )}
    </article>
  );
}
