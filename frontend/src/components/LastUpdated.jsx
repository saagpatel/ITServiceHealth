import { useState, useEffect } from "react";
import { STALE_WARNING_MS, STALE_CRITICAL_MS } from "../lib/constants";

export default function LastUpdated({ lastUpdated }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  if (!lastUpdated) {
    return (
      <div className="fixed bottom-0 left-0 right-0 h-8 bg-bg-card border-t border-border flex items-center justify-center">
        <span className="text-xs text-text-muted">Connecting...</span>
      </div>
    );
  }

  const age = Date.now() - lastUpdated;
  const seconds = Math.floor(age / 1000);

  let label;
  if (seconds < 60) label = `${seconds}s ago`;
  else if (seconds < 3600) label = `${Math.floor(seconds / 60)}m ago`;
  else label = `${Math.floor(seconds / 3600)}h ago`;

  let textClass = "text-text-muted";
  if (age > STALE_CRITICAL_MS) textClass = "text-status-major";
  else if (age > STALE_WARNING_MS) textClass = "text-status-degraded";

  return (
    <div className="fixed bottom-0 left-0 right-0 h-8 bg-bg-card border-t border-border flex items-center justify-center">
      <span className={`text-xs ${textClass}`}>Last updated {label}</span>
    </div>
  );
}
