import { useMemo } from "react";
import { usePolling } from "./use-polling";
import {
  POLL_INTERVAL_MS,
  UPTIME_POLL_INTERVAL_MS,
  STALE_WARNING_MS,
} from "../lib/constants";
import {
  EXEC_SLA_TARGET,
  EXEC_IMPACT_LIMIT,
  STATUS_RANK,
} from "../lib/executive-tokens";

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
 * @property {Error|null} error
 */

// Repo rule (root CLAUDE.md): a service whose poller is broken must never
// render as operational — surface as unknown regardless of vendor signal.
function computeStatus(service) {
  if (!service) return "unknown";
  if (service.poller_health === "broken") return "unknown";
  return service.current_status || "unknown";
}

function weightedSlaMean(services) {
  const vals = [];
  for (const s of services) {
    const v = s?.uptime_30d;
    if (typeof v === "number" && Number.isFinite(v)) vals.push(v);
  }
  if (vals.length === 0) return null;
  const sum = vals.reduce((acc, v) => acc + v, 0);
  return sum / vals.length;
}

function buildImpactRows(servicesList, activeIncidents) {
  // Index incidents by service id so impact lines land on the right row.
  const incidentByService = new Map();
  for (const inc of activeIncidents || []) {
    const sid = inc?.service?.id;
    if (sid && !incidentByService.has(sid)) incidentByService.set(sid, inc);
  }

  const rows = [];
  for (const s of servicesList || []) {
    const status = computeStatus(s);
    if (status === "operational") continue;
    const inc = incidentByService.get(s.id);
    rows.push({
      id: s.id,
      label: s.display_name || s.id,
      category: s.category || "",
      status,
      isPollerBroken: s.poller_health === "broken",
      impactLine:
        inc?.impact_statement ||
        `${s.display_name || s.id}: ${status.replace(/_/g, " ")}`,
      sinceIso: s.last_status_change_at || null,
    });
  }

  rows.sort((a, b) => {
    const rankDiff = (STATUS_RANK[b.status] ?? 0) - (STATUS_RANK[a.status] ?? 0);
    if (rankDiff !== 0) return rankDiff;
    // Most-recent change first within the same severity.
    const ax = a.sinceIso ? Date.parse(a.sinceIso) : 0;
    const bx = b.sinceIso ? Date.parse(b.sinceIso) : 0;
    return bx - ax;
  });

  return rows.slice(0, EXEC_IMPACT_LIMIT);
}

function aggregateTrend(historyData) {
  const days = historyData?.days || [];
  const servicesMap = historyData?.services || {};
  const byDate = new Map();
  for (const day of days) byDate.set(day, { sum: 0, count: 0, anyDegraded: false });

  for (const points of Object.values(servicesMap)) {
    for (const p of points || []) {
      const slot = byDate.get(p.date);
      if (!slot) continue;
      if (typeof p.uptime === "number" && Number.isFinite(p.uptime)) {
        slot.sum += p.uptime;
        slot.count += 1;
        if (p.uptime < 100) slot.anyDegraded = true;
      }
    }
  }

  return days.map((date) => {
    const slot = byDate.get(date);
    const uptimePct = slot && slot.count > 0 ? slot.sum / slot.count : null;
    return { date, uptimePct, anyDegraded: !!slot?.anyDegraded };
  });
}

function buildHeadline(overallStatus, incidentsOpen) {
  if (overallStatus === "operational" && incidentsOpen === 0) {
    return "All Systems Operational";
  }
  if (incidentsOpen === 1) return "Active Incident";
  if (incidentsOpen > 1) return `${incidentsOpen} Active Incidents`;
  // Edge: non-operational overall but no active_incidents rows (e.g., poller broken).
  return "Service Degradation";
}

/**
 * Composes /api/summary + /api/services + /api/services/sla +
 * /api/services/sla/history?days=30 into a single memoized shape for the
 * Executive view. Fetches unwrap the {data, error, meta} envelope at the
 * lib/api.js boundary, so e.g. `summary.data.overall_status` is the inner
 * payload directly.
 *
 * @returns {ExecutiveData}
 */
export function useExecutiveData() {
  const summary = usePolling("/api/summary", POLL_INTERVAL_MS);
  const services = usePolling("/api/services", POLL_INTERVAL_MS);
  const sla = usePolling("/api/services/sla", UPTIME_POLL_INTERVAL_MS);
  const history = usePolling(
    "/api/services/sla/history?days=30",
    UPTIME_POLL_INTERVAL_MS,
  );

  const lastUpdatedMs = useMemo(() => {
    const stamps = [
      summary.lastUpdated,
      services.lastUpdated,
      sla.lastUpdated,
      history.lastUpdated,
    ].filter((t) => typeof t === "number");
    return stamps.length > 0 ? Math.max(...stamps) : null;
  }, [summary.lastUpdated, services.lastUpdated, sla.lastUpdated, history.lastUpdated]);

  const error =
    summary.error || services.error || sla.error || history.error || null;

  const base = useMemo(() => {
    const summaryData = summary.data || {};
    const servicesList = services.data?.services || [];
    const slaMap = sla.data?.services || {};

    // Merge each service row with its SLA uptime so weightedSlaMean and
    // impact rows share one shape.
    const enriched = servicesList.map((s) => ({
      ...s,
      uptime_30d: slaMap[s.id]?.uptime_30d ?? null,
    }));

    const overallStatus = summaryData.overall_status || "unknown";
    const activeIncidents = summaryData.active_incidents || [];
    const incidentsOpen = activeIncidents.length;

    const vendorsDegraded = enriched.filter((s) => {
      const st = computeStatus(s);
      return st !== "operational" && st !== "unknown";
    }).length;

    const totalServices = summaryData.total_services ?? enriched.length;
    const unknownCount = summaryData.unknown_count ?? 0;
    const totalMonitored = Math.max(0, totalServices - unknownCount);

    const slaObserved = weightedSlaMean(enriched);
    const slaDeltaBps =
      slaObserved !== null ? (slaObserved - EXEC_SLA_TARGET) * 100 : null;

    const impact = buildImpactRows(enriched, activeIncidents);
    const trend = aggregateTrend(history.data);

    return {
      overallStatus,
      headline: buildHeadline(overallStatus, incidentsOpen),
      incidentsOpen,
      vendorsDegraded,
      totalMonitored,
      slaTarget: EXEC_SLA_TARGET,
      slaObserved,
      slaDeltaBps,
      impact,
      trend,
      lastUpdatedMs,
      error,
    };
  }, [summary.data, services.data, sla.data, history.data, lastUpdatedMs, error]);

  // App.jsx's setStaleTick re-renders every second so this "now" reading
  // stays fresh — same pattern App.jsx already uses for its last-poll clock.
  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();
  const isStale =
    lastUpdatedMs !== null && now - lastUpdatedMs > STALE_WARNING_MS;

  return { ...base, isStale };
}
