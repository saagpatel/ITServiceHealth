import { useRef, useState } from "react";
import {
  CATEGORY_ORDER,
  STATUS_COLORS,
  STATUS_ICON_COMPONENTS,
  STATUS_SEVERITY_RANK,
  effectiveStatus,
} from "../lib/constants";
import ServiceTile from "./ServiceTile";

/**
 * Category + service grid.
 *
 * Phase 5 contract:
 *   - Categories are sorted worst-first so leadership never scans for the
 *     one red tile; the worst service lives in the top-left.
 *   - Inside a category, tiles sort by severity rank (from
 *     STATUS_SEVERITY_RANK), with `unmonitored` (manual+unknown) sunk
 *     to the bottom because they're always visually quiet.
 *   - `effectiveStatus(svc)` forces `unknown` when the poller is broken,
 *     so worst-first reflects real knowability — services we're blind
 *     about pop above "operational" in the sort.
 *   - The grid exposes `role="grid"` + roving tabindex so keyboard users
 *     can walk it with j/k or arrow keys.
 */
export default function ServiceGrid({ services, slaData, onSelect }) {
  const gridRef = useRef(null);
  const [focusedId, setFocusedId] = useState(null);

  if (!services?.services) {
    return (
      <div className="space-y-6" aria-label="Loading services" role="status">
        {[...Array(4)].map((_, i) => (
          <div key={i}>
            <div className="h-3 w-36 bg-bg-surface rounded animate-pulse mb-3" />
            <div className="grid grid-cols-4 gap-2">
              {[...Array(4)].map((_, j) => (
                <div
                  key={j}
                  className="h-[72px] bg-bg-surface rounded-lg animate-pulse"
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  const servicesByCategory = {};
  for (const svc of services.services) {
    if (!servicesByCategory[svc.category]) servicesByCategory[svc.category] = [];
    servicesByCategory[svc.category].push(svc);
  }

  // Worst-first category ordering
  const categoryOrder = [...CATEGORY_ORDER].sort((a, b) => {
    return worstRank(servicesByCategory[b.key]) - worstRank(servicesByCategory[a.key]);
  });

  // Flat list of service IDs in render order, for j/k nav
  const orderedIds = [];
  for (const { key } of categoryOrder) {
    const svcs = servicesByCategory[key];
    if (!svcs?.length) continue;
    for (const svc of [...svcs].sort(sortWorstFirst)) {
      orderedIds.push(svc.id);
    }
  }

  const focusTile = (id) => {
    if (!id) return;
    setFocusedId(id);
    gridRef.current
      ?.querySelector(`[data-service-id="${CSS.escape(id)}"]`)
      ?.focus();
  };

  const handleKey = (e) => {
    if (!orderedIds.length) return;
    const idx = orderedIds.indexOf(focusedId);
    const pivot = idx < 0 ? 0 : idx;

    if (e.key === "j" || e.key === "ArrowRight" || e.key === "ArrowDown") {
      focusTile(orderedIds[Math.min(orderedIds.length - 1, pivot + 1)]);
      e.preventDefault();
    } else if (e.key === "k" || e.key === "ArrowLeft" || e.key === "ArrowUp") {
      focusTile(orderedIds[Math.max(0, pivot - 1)]);
      e.preventDefault();
    } else if (e.key === "Home") {
      focusTile(orderedIds[0]);
      e.preventDefault();
    } else if (e.key === "End") {
      focusTile(orderedIds[orderedIds.length - 1]);
      e.preventDefault();
    } else if (e.key === "Enter" && idx >= 0) {
      onSelect(orderedIds[idx]);
      e.preventDefault();
    }
  };

  // Tab into the grid lands on the first (worst) tile by default
  const firstId = orderedIds[0];
  const activeTabId = focusedId || firstId;

  return (
    <div
      ref={gridRef}
      role="grid"
      aria-label="Service status grid"
      className="space-y-5"
      onKeyDown={handleKey}
    >
      {categoryOrder.map(({ key, label }) => {
        const svcs = servicesByCategory[key];
        if (!svcs || svcs.length === 0) return null;

        const sorted = [...svcs].sort(sortWorstFirst);

        const degradedCount = svcs.filter((s) => {
          const eff = effectiveStatus(s);
          return eff !== "operational" && eff !== "unknown";
        }).length;
        const unknownCount = svcs.filter(
          (s) => effectiveStatus(s) === "unknown",
        ).length;

        const worstStatus = svcs.reduce((worst, s) => {
          const eff = effectiveStatus(s);
          return (STATUS_SEVERITY_RANK[eff] ?? 0) >
            (STATUS_SEVERITY_RANK[worst] ?? 0)
            ? eff
            : worst;
        }, "operational");

        const showRollup = degradedCount > 0 || unknownCount > 0;
        const rollupColor = showRollup
          ? STATUS_COLORS[worstStatus]
          : STATUS_COLORS.operational;
        const RollupIcon = showRollup
          ? STATUS_ICON_COMPONENTS[worstStatus]
          : STATUS_ICON_COMPONENTS.operational;
        const rollupText = showRollup
          ? [
              degradedCount > 0 &&
                `${degradedCount} issue${degradedCount !== 1 ? "s" : ""}`,
              unknownCount > 0 && `${unknownCount} blind`,
            ]
              .filter(Boolean)
              .join(" · ")
          : "all ok";

        return (
          <div key={key} role="rowgroup">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-[11px] uppercase tracking-wider text-text-secondary font-semibold">
                {label}
              </h3>
              <span
                className="text-[11px] flex items-center gap-1"
                style={{ color: rollupColor }}
              >
                <RollupIcon size={12} strokeWidth={2.5} /> {rollupText}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-2" role="row">
              {sorted.map((svc) => (
                <ServiceTile
                  key={svc.id}
                  service={svc}
                  uptimePercent={
                    slaData?.services?.[svc.id]?.uptime_7d ?? null
                  }
                  onClick={onSelect}
                  onFocus={setFocusedId}
                  tabIndex={svc.id === activeTabId ? 0 : -1}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function worstRank(svcs) {
  if (!svcs?.length) return -1;
  let worst = -1;
  for (const s of svcs) {
    const rank = STATUS_SEVERITY_RANK[effectiveStatus(s)] ?? 0;
    if (rank > worst) worst = rank;
  }
  return worst;
}

function sortWorstFirst(a, b) {
  const aUnmonitored =
    a.poll_type === "manual" &&
    a.current_status === "unknown" &&
    a.poller_health !== "broken";
  const bUnmonitored =
    b.poll_type === "manual" &&
    b.current_status === "unknown" &&
    b.poller_health !== "broken";
  if (aUnmonitored !== bUnmonitored) return aUnmonitored ? 1 : -1;

  const aRank = STATUS_SEVERITY_RANK[effectiveStatus(a)] ?? 0;
  const bRank = STATUS_SEVERITY_RANK[effectiveStatus(b)] ?? 0;
  if (aRank !== bRank) return bRank - aRank;
  return a.display_name.localeCompare(b.display_name);
}
