import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { STATUS_COLORS } from "../lib/constants";

export default function SlaChart({ dataPoints }) {
  if (!dataPoints || dataPoints.length === 0) {
    return (
      <div className="h-[160px] bg-bg-surface rounded-lg flex items-center justify-center">
        <span className="text-xs text-text-muted">No SLA history available</span>
      </div>
    );
  }

  // Filter out null uptimes for chart display, keep dates for axis
  const chartData = dataPoints.map((p) => ({
    date: p.date,
    uptime: p.uptime,
    // Short label for X axis: "Apr 1"
    label: new Date(p.date + "T00:00:00").toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
  }));

  // Auto-adjust Y axis — default 96-100, but lower if data dips below
  const minUptime = Math.min(
    ...chartData.filter((d) => d.uptime !== null).map((d) => d.uptime)
  );
  const yMin = Math.min(96, Math.floor(minUptime - 1));

  return (
    <div className="h-[160px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="slaGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={STATUS_COLORS.operational} stopOpacity={0.3} />
              <stop offset="95%" stopColor={STATUS_COLORS.operational} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[yMin, 100]}
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#151d2e",
              border: "1px solid #1e293b",
              borderRadius: "8px",
              fontSize: "12px",
            }}
            labelStyle={{ color: "#94a3b8" }}
            formatter={(value) => [
              value !== null ? `${value.toFixed(2)}%` : "No data",
              "Uptime",
            ]}
          />
          <ReferenceLine
            y={99.9}
            stroke={STATUS_COLORS.degraded}
            strokeDasharray="4 4"
            strokeOpacity={0.5}
          />
          <Area
            type="monotone"
            dataKey="uptime"
            stroke={STATUS_COLORS.operational}
            strokeWidth={1.5}
            fill="url(#slaGradient)"
            connectNulls
            dot={false}
            activeDot={{ r: 3, fill: STATUS_COLORS.operational }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
