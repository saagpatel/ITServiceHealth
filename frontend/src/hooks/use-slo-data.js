import { useMemo } from "react";
import { usePolling } from "./use-polling";
import { STALE_WARNING_MS } from "../lib/constants";
import { SLO_POLL_INTERVAL_MS } from "../lib/slo-tokens";

/**
 * @typedef {Object} SloService
 * @property {string} id
 * @property {string} display_name
 * @property {string} category
 * @property {string} tier
 * @property {string} current_status
 * @property {string} poller_health
 * @property {number|null} uptime_30d_pct
 * @property {number} error_budget_remaining_pct
 * @property {boolean} fast_burning
 * @property {boolean} slow_burning
 * @property {Object|null} fast_breach
 * @property {Object|null} slow_breach
 */

/**
 * @typedef {Object} SloData
 * @property {SloService[]} services
 * @property {Object|null} thresholds
 * @property {number} burningCount
 * @property {number|null} lastUpdatedMs
 * @property {boolean} isStale
 * @property {boolean} loading
 * @property {Error|null} error
 */

/**
 * Composes GET /api/services/slo into a memoized, sorted shape for the SLO view.
 * Services are sorted by burn severity desc, then budget asc, then display_name.
 *
 * @returns {SloData}
 */
export function useSloData() {
  const slo = usePolling("/api/services/slo", SLO_POLL_INTERVAL_MS);

  const base = useMemo(() => {
    const services = slo.data?.services || [];
    const thresholds = slo.data?.thresholds || null;
    const sorted = [...services].sort((a, b) => {
      const burnA = a.fast_burning ? 2 : a.slow_burning ? 1 : 0;
      const burnB = b.fast_burning ? 2 : b.slow_burning ? 1 : 0;
      if (burnA !== burnB) return burnB - burnA;
      const budA = a.error_budget_remaining_pct ?? 100;
      const budB = b.error_budget_remaining_pct ?? 100;
      if (budA !== budB) return budA - budB;
      return (a.display_name || "").localeCompare(b.display_name || "");
    });
    const burningCount = sorted.filter(s => s.fast_burning || s.slow_burning).length;
    return { services: sorted, thresholds, burningCount };
  }, [slo.data]);

  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();
  const isStale =
    slo.lastUpdated !== null && now - slo.lastUpdated > STALE_WARNING_MS;

  return { ...base, lastUpdatedMs: slo.lastUpdated, isStale, loading: slo.loading, error: slo.error };
}
