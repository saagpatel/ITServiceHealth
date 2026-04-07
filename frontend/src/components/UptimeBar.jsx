import { STATUS_COLORS } from "../lib/constants";

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export default function UptimeBar({ days, serviceUptime }) {
  if (!days || days.length === 0) {
    return <div className="flex gap-[2px] items-center opacity-30">
      {[...Array(7)].map((_, i) => (
        <div key={i} className="w-4 h-6 rounded-sm bg-border" />
      ))}
    </div>;
  }

  return (
    <div className="flex gap-[2px] items-center" role="img" aria-label="7-day uptime history">
      {days.map((day) => {
        const status = serviceUptime?.[day] || "operational";
        const color = STATUS_COLORS[status] || STATUS_COLORS.operational;
        const date = new Date(day + "T00:00:00");
        const dayName = DAY_NAMES[date.getDay()];
        const label = `${dayName} ${day}: ${status.replace(/_/g, " ")}`;

        return (
          <div
            key={day}
            className="w-4 h-6 rounded-sm transition-opacity hover:opacity-80 cursor-default"
            style={{ backgroundColor: color }}
            title={label}
          />
        );
      })}
    </div>
  );
}
