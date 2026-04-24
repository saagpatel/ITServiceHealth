import {
  Area,
  AreaChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EXEC_TREND_COLORS } from "../../lib/executive-tokens";

/** 30-day mean uptime strip, oldest left to newest right.
 *
 *  Axis labels are intentionally hidden — at conference-room distance
 *  the strip is a shape the viewer reads pre-verbally: mostly flat + a
 *  couple of red notches means "we had a rough couple of days but we're
 *  back". Hovering reveals the exact date and percentage. Days where
 *  any service dipped below 100 % render a vertical alarm-red
 *  ReferenceLine. */
function TrendTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0].payload;
  const value =
    point.uptimePct === null || point.uptimePct === undefined
      ? "no data"
      : `${point.uptimePct.toFixed(2)}%`;
  return (
    <div
      className="bg-surface-elev-2 border border-border rounded-md px-3 py-2 text-exec-body font-mono"
      data-tabular="true"
    >
      <div className="text-text-dim">{point.date}</div>
      <div className="text-text-display">{value}</div>
    </div>
  );
}

export default function ExecutiveTrendStrip({ exec }) {
  const { trend, loading } = exec;

  if (loading) {
    return (
      <section
        aria-label="30-day uptime trend"
        className="bg-surface-elev-1 border border-border rounded-2xl h-44 animate-pulse"
      />
    );
  }

  const hasData = Array.isArray(trend) && trend.length > 0;
  const hasAny =
    hasData &&
    trend.some((p) => p.uptimePct !== null && p.uptimePct !== undefined);

  if (!hasAny) {
    return (
      <section
        aria-label="30-day uptime trend"
        className="bg-surface-elev-1 border border-border rounded-2xl h-44 flex items-center justify-center"
      >
        <p className="text-exec-body text-text-dim">
          Gathering history — trend appears once there are enough poll cycles.
        </p>
      </section>
    );
  }

  // Compute observed range so the area magnifies real dips instead of
  // collapsing into a flat line against a 0-100 axis.
  const values = trend
    .map((p) => p.uptimePct)
    .filter((v) => v !== null && v !== undefined);
  const observedMin = Math.min(...values);
  const yMin = Math.max(0, Math.floor(observedMin - 0.5));
  const headlineRange =
    values.length > 0
      ? `${observedMin.toFixed(2)} – 100.00 %`
      : "no data";

  return (
    <section
      aria-label="30-day uptime trend"
      className="bg-surface-elev-1 border border-border rounded-2xl px-6 pt-5 pb-4"
    >
      <header className="flex items-center justify-between mb-2">
        <h3 className="text-exec-body text-text-dim">30-day uptime</h3>
        <span
          className="text-exec-body font-mono text-text-dim"
          data-tabular="true"
        >
          {headlineRange}
        </span>
      </header>

      <div className="h-28">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={trend}
            margin={{ top: 4, right: 4, bottom: 0, left: 4 }}
          >
            <defs>
              <linearGradient id="execTrendFill" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="0%"
                  stopColor={EXEC_TREND_COLORS.surfaceElev2}
                  stopOpacity={0.95}
                />
                <stop
                  offset="100%"
                  stopColor={EXEC_TREND_COLORS.surfaceElev2}
                  stopOpacity={0.35}
                />
              </linearGradient>
            </defs>
            {/* Axes are declared so ReferenceLine x-values can resolve.
                `hide` keeps the ticks and gridlines off the screen — the
                roadmap specifies an axis-less visual, not an axis-less
                component tree. */}
            <XAxis dataKey="date" hide />
            <YAxis domain={[yMin, 100]} hide />
            <Tooltip
              cursor={{ stroke: EXEC_TREND_COLORS.border, strokeWidth: 1 }}
              content={<TrendTooltip />}
            />
            {trend
              .filter((p) => p.anyDegraded)
              .map((p) => (
                <ReferenceLine
                  key={p.date}
                  x={p.date}
                  stroke={EXEC_TREND_COLORS.accentAlarm}
                  strokeOpacity={0.8}
                  strokeWidth={1.25}
                  ifOverflow="extendDomain"
                />
              ))}
            <Area
              type="monotone"
              dataKey="uptimePct"
              stroke={EXEC_TREND_COLORS.textDisplay}
              strokeWidth={1.5}
              fill="url(#execTrendFill)"
              connectNulls
              isAnimationActive={false}
              dot={false}
              activeDot={{
                r: 4,
                fill: EXEC_TREND_COLORS.textDisplay,
                stroke: EXEC_TREND_COLORS.surfaceElev1,
                strokeWidth: 2,
              }}
              baseValue={yMin}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
