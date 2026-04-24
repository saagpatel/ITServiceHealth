import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  ReferenceLine,
} from "recharts";
import { EXEC_CHART_COLORS } from "../../lib/executive-tokens";

function formatDay(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function TrendTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const pct =
    typeof p.uptimePct === "number" && Number.isFinite(p.uptimePct)
      ? `${p.uptimePct.toFixed(2)}%`
      : "No data";
  return (
    <div className="bg-surface-elev-2 border border-white/10 rounded-md px-3 py-2 text-body font-mono">
      <div className="text-text-dim">{formatDay(p.date)}</div>
      <div className="text-text-display" data-tabular="true">
        {pct}
      </div>
    </div>
  );
}

export default function ExecutiveTrendStrip({ trend }) {
  if (!trend || trend.length === 0) {
    return (
      <div className="bg-surface-elev-1 rounded-lg px-8 py-10">
        <p className="text-body uppercase tracking-[0.12em] text-text-dim mb-2">
          Uptime · last 30 days
        </p>
        <p className="text-body text-text-dim">Gathering history…</p>
      </div>
    );
  }

  const degradedDays = trend.filter((t) => t.anyDegraded).map((t) => t.date);

  return (
    <div className="bg-surface-elev-1 rounded-lg px-8 py-8">
      <div className="flex items-baseline justify-between mb-4">
        <span className="text-body uppercase tracking-[0.12em] text-text-dim">
          Uptime · last 30 days
        </span>
        <span className="text-body text-text-dim">
          {degradedDays.length === 0
            ? "No degraded days"
            : `${degradedDays.length} degraded day${degradedDays.length === 1 ? "" : "s"}`}
        </span>
      </div>
      <div className="h-28">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={trend}
            margin={{ top: 4, right: 4, bottom: 4, left: 4 }}
          >
            <defs>
              <linearGradient id="execTrendFill" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="0%"
                  stopColor={EXEC_CHART_COLORS.surfaceElev2}
                  stopOpacity={0.95}
                />
                <stop
                  offset="100%"
                  stopColor={EXEC_CHART_COLORS.surfaceElev2}
                  stopOpacity={0.2}
                />
              </linearGradient>
            </defs>
            {/* Axes are hidden but must exist so ReferenceLine x/y can position. */}
            <XAxis dataKey="date" hide allowDuplicatedCategory={false} />
            <YAxis hide domain={[(min) => Math.floor(min - 1), 100]} />
            {degradedDays.map((d) => (
              <ReferenceLine
                key={d}
                x={d}
                stroke={EXEC_CHART_COLORS.accentAlarm}
                strokeWidth={1.5}
                strokeOpacity={0.85}
              />
            ))}
            <Area
              type="monotone"
              dataKey="uptimePct"
              stroke={EXEC_CHART_COLORS.textDisplay}
              strokeWidth={1.5}
              fill="url(#execTrendFill)"
              connectNulls={false}
              isAnimationActive={false}
              dot={false}
              activeDot={{
                r: 3,
                fill: EXEC_CHART_COLORS.textDisplay,
                stroke: "none",
              }}
            />
            <Tooltip
              content={<TrendTooltip />}
              cursor={{
                stroke: EXEC_CHART_COLORS.textDim,
                strokeDasharray: "3 3",
              }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
