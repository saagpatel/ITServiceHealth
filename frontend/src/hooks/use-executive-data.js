import { useMemo } from "react";
import { usePolling } from "./use-polling";
import {
  POLL_INTERVAL_MS,
  UPTIME_POLL_INTERVAL_MS,
  STALE_CRITICAL_MS,
  STATUS_SEVERITY_RANK,
  effectiveStatus,
  isPollerBroken,
} from "../lib/constants";
import { EXEC_SLA_TARGET, EXEC_IMPACT_LIMIT } from "../lib/executive-tokens";

/**
 * @typedef {Object} ImpactRow
 * @property {string} id
 * @property {string} label
 * @property {string} category
 * @property {"degraded"|"partial_outage"|"major_outage"|"unknown"} status
 * @property {boolean} isPollerBroken
 * @property {string} impactLine
 * @property {string|null} sinceIso
 */

/**
 * @typedef {Object} TrendPoint
 * @property {string} date
 * @property {number|null} uptimePct
 * @property {boolean} anyDegraded
 */

/**
 * @typedef {Object} ExecutiveData
 * @property {"operational"|"degraded"|"partial_outage"|"major_outage"|"unknown"} overallStatus
 * @property {string} headline
 * @property {number} incidentsOpen
 * @property {number} vendorsDegraded
 * @property {number} totalMonitored
 * @property {number} slaTarget
 * @property {number|null} slaObserved
 * @property {number|null} slaDeltaBps
 * @property {ImpactRow[]} impact
 * @property {TrendPoint[]} trend
 * @property {number|null} lastUpdatedMs
 * @property {boolean} isStale
 * @property {boolean} loading
 * @property {Error|null} error
 */

/** Composes the four backend endpoints the Executive view needs and
 *  returns a single memoized `ExecutiveData` object.
 *
 *  All upstream polls run on `usePolling`'s normal cadence (30 s for
 *  status, 5 min for SLA + history). Memoization is keyed on the raw
 *  fetch payloads so the 1-Hz stale-tick in `App.jsx` doesn't re-derive
 *  KPIs on every render. */
export function useExecutiveData() {
  const summary = usePolling("/api/summary", POLL_INTERVAL_MS);
  const services = usePolling("/api/services", POLL_INTERVAL_MS);
  const sla = usePolling("/api/services/sla", UPTIME_POLL_INTERVAL_MS);
  const history = usePolling(
    "/api/services/sla/history?days=30",
    UPTIME_POLL_INTERVAL_MS,
  );

  return useMemo(() => {
    /** @type {ExecutiveData} */
    const base = {
      overallStatus: "unknown",
      headline: "Loading…",
      incidentsOpen: 0,
      vendorsDegraded: 0,
      totalMonitored: 0,
      slaTarget: EXEC_SLA_TARGET,
      slaObserved: null,
      slaDeltaBps: null,
      impact: [],
      trend: [],
      lastUpdatedMs: summary.lastUpdated ?? null,
      isStale: false,
      loading: summary.loading || services.loading,
      error: summary.error || services.error || sla.error || history.error || null,
    };

    if (!summary.data || !services.data) return base;

    const sList = Array.isArray(services.data.services)
      ? services.data.services
      : [];
    const activeIncidents = Array.isArray(summary.data.active_incidents)
      ? summary.data.active_incidents
      : [];

    // Headline + counts ---------------------------------------------------
    const overallStatus = summary.data.overall_status || "unknown";
    const incidentsOpen = activeIncidents.length;
    const vendorsDegraded = sList.filter((s) => {
      const st = effectiveStatus(s);
      return st !== "operational" && st !== "unknown";
    }).length;
    const totalMonitored =
      (summary.data.total_services ?? sList.length) -
      (summary.data.unknown_count ?? 0);

    let headline;
    if (incidentsOpen === 0) headline = "All Systems Operational";
    else if (incidentsOpen === 1) headline = "1 Active Incident";
    else headline = `${incidentsOpen} Active Incidents`;

    // SLA observed / delta ------------------------------------------------
    let slaObserved = null;
    let slaDeltaBps = null;
    const slaServices = sla.data?.services;
    if (slaServices && typeof slaServices === "object") {
      const values = Object.values(slaServices)
        .map((row) => row?.uptime_30d)
        .filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
      if (values.length > 0) {
        slaObserved =
          values.reduce((sum, v) => sum + v, 0) / values.length;
        slaDeltaBps = Math.round((slaObserved - EXEC_SLA_TARGET) * 100);
      }
    }

    // Impact list ---------------------------------------------------------
    // Prefer active_incidents from /api/summary because it carries the
    // templated impact_statement. Fall back to service rows for services
    // with non-operational status but no incident row (covers the gap
    // between a state change and the impact-engine run).
    const impactBySvcId = new Map();
    for (const inc of activeIncidents) {
      const svc = inc.service || {};
      const id = svc.id;
      if (!id) continue;
      impactBySvcId.set(id, {
        id,
        label: svc.display_name || id,
        category: svc.category || "",
        status: svc.current_status || "unknown",
        isPollerBroken: svc.poller_health === "broken",
        impactLine:
          inc.impact_statement ||
          `${svc.display_name || id} status: ${svc.current_status || "unknown"}`,
        sinceIso: inc.started_at || svc.last_status_change_at || null,
      });
    }
    for (const svc of sList) {
      const st = effectiveStatus(svc);
      if (st === "operational") continue;
      if (impactBySvcId.has(svc.id)) continue;
      // Skip unknown-on-boot — only show unknown when poller is actually
      // broken, otherwise a freshly-added service would appear in impact.
      if (st === "unknown" && !isPollerBroken(svc)) continue;
      impactBySvcId.set(svc.id, {
        id: svc.id,
        label: svc.display_name || svc.id,
        category: svc.category || "",
        status: st,
        isPollerBroken: isPollerBroken(svc),
        impactLine: isPollerBroken(svc)
          ? `Poller broken — last successful reading is stale`
          : `${svc.display_name || svc.id} reporting ${st.replace("_", " ")}`,
        sinceIso: svc.last_status_change_at || null,
      });
    }
    const impact = [...impactBySvcId.values()]
      .sort((a, b) => {
        const ra = STATUS_SEVERITY_RANK[a.status] ?? 0;
        const rb = STATUS_SEVERITY_RANK[b.status] ?? 0;
        if (rb !== ra) return rb - ra;
        // Newer state changes first inside the same severity bucket
        return (b.sinceIso || "").localeCompare(a.sinceIso || "");
      })
      .slice(0, EXEC_IMPACT_LIMIT);

    // 30-day trend --------------------------------------------------------
    // Backend returns per-service daily points. For the Executive view we
    // want a single strip: mean uptime across monitored services per day,
    // plus a boolean flag when any service dipped below 100 % (used to
    // mark alarm-red days on the strip).
    const historyData = history.data;
    const trend = [];
    if (historyData?.days && historyData?.services) {
      const days = historyData.days;
      const svcMap = historyData.services;
      const svcIds = Object.keys(svcMap);
      for (const day of days) {
        let sum = 0;
        let n = 0;
        let anyDegraded = false;
        for (const sid of svcIds) {
          const points = svcMap[sid] || [];
          const point = points.find((p) => p.date === day);
          if (point && point.uptime !== null && point.uptime !== undefined) {
            sum += point.uptime;
            n += 1;
            if (point.uptime < 100) anyDegraded = true;
          }
        }
        trend.push({
          date: day,
          uptimePct: n > 0 ? sum / n : null,
          anyDegraded,
        });
      }
    }

    // Staleness -----------------------------------------------------------
    // `isStale` is a time-based check — App.jsx's 1-Hz stale tick drives
    // re-renders, so reading Date.now() here gives a fresh answer per
    // render without needing its own timer. Mirrors the precedent in
    // App.jsx where the same rule is disabled for the same reason.
    const lastUpdatedMs = summary.lastUpdated ?? null;
    // eslint-disable-next-line react-hooks/purity
    const now = Date.now();
    const isStale =
      lastUpdatedMs !== null && now - lastUpdatedMs > STALE_CRITICAL_MS;

    return {
      overallStatus,
      headline,
      incidentsOpen,
      vendorsDegraded,
      totalMonitored,
      slaTarget: EXEC_SLA_TARGET,
      slaObserved,
      slaDeltaBps,
      impact,
      trend,
      lastUpdatedMs,
      isStale,
      loading: false,
      error: null,
    };
  }, [
    summary.data,
    summary.lastUpdated,
    summary.loading,
    summary.error,
    services.data,
    services.loading,
    services.error,
    sla.data,
    sla.error,
    history.data,
    history.error,
  ]);
}
