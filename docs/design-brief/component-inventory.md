# Pulse — Component Inventory

Every React component in `frontend/src/components/` + its role. Claude Design should propose a treatment for each. Paths are relative to repo root.

## Shell + layout

| Component | File | What it does |
|-----------|------|--------------|
| `App` / `AppContent` | [`frontend/src/App.jsx`](../../frontend/src/App.jsx) | Top-level. Provides `ViewProvider`, polls APIs, renders layout, owns global keyboard shortcuts. |
| `ViewProvider` / `useView` | [`frontend/src/contexts/ViewContext.jsx`](../../frontend/src/contexts/ViewContext.jsx) | React context for Executive / Engineer mode toggle. |
| `ViewToggle` | [`frontend/src/components/ViewToggle.jsx`](../../frontend/src/components/ViewToggle.jsx) | Segmented control in the header that flips the view. |

## Headline status

| Component | File | Role |
|-----------|------|------|
| `StatusBanner` | [`frontend/src/components/StatusBanner.jsx`](../../frontend/src/components/StatusBanner.jsx) | Big pill at the top: "All systems operational" / "N active incidents". Color follows overall severity. |
| `IncidentSection` | [`frontend/src/components/IncidentSection.jsx`](../../frontend/src/components/IncidentSection.jsx) | List of currently-affected services with impact statements. Appears only when `active_incidents.length > 0`. |
| `MaintenanceBanner` | [`frontend/src/components/MaintenanceBanner.jsx`](../../frontend/src/components/MaintenanceBanner.jsx) | Upcoming vendor maintenance windows. Collapsible. |
| `ErrorBanner` | [`frontend/src/components/ErrorBanner.jsx`](../../frontend/src/components/ErrorBanner.jsx) | Aggregates fetch failures from the frontend's own API polls. Sits under the header when any poll is erroring. |

## The grid (Engineer)

| Component | File | Role |
|-----------|------|------|
| `ServiceGrid` | [`frontend/src/components/ServiceGrid.jsx`](../../frontend/src/components/ServiceGrid.jsx) | Full service grid with category sections. Implements severity sort, worst-first ordering, roving tabindex, keyboard nav. |
| `ServiceTile` | [`frontend/src/components/ServiceTile.jsx`](../../frontend/src/components/ServiceTile.jsx) | One tile. Handles three visual modes: monitored, unmonitored, poller-broken. Renders flapping badge + uptime %. |
| `StatusIndicator` | [`frontend/src/components/StatusIndicator.jsx`](../../frontend/src/components/StatusIndicator.jsx) | Small icon + text indicator reused inline (e.g., category rollups, detail drawer). |
| `UptimeBar` | [`frontend/src/components/UptimeBar.jsx`](../../frontend/src/components/UptimeBar.jsx) | 7-day per-service segmented uptime strip (one segment per day, colored by worst status that day). |

## The rollup (Executive)

| Component | File | Role |
|-----------|------|------|
| `CategorySummary` | [`frontend/src/components/CategorySummary.jsx`](../../frontend/src/components/CategorySummary.jsx) | Replaces `ServiceGrid` in Executive mode. One card per category with rollup status + SLA number. Calmer, more whitespace. |

## Drill-down

| Component | File | Role |
|-----------|------|------|
| `ServiceDetail` | [`frontend/src/components/ServiceDetail.jsx`](../../frontend/src/components/ServiceDetail.jsx) | Right-side drawer that opens when a tile is clicked. Shows dependencies (upstream + downstream), recent status events, SLA trend chart. |
| `SlaChart` | [`frontend/src/components/SlaChart.jsx`](../../frontend/src/components/SlaChart.jsx) | `recharts` line chart for 30-day uptime % history. Lives inside `ServiceDetail`. |
| `DependencyGraph` | [`frontend/src/components/DependencyGraph.jsx`](../../frontend/src/components/DependencyGraph.jsx) | Full-viewport overlay: force-directed service dependency graph. Toggled with `g`. Engineer mode only. Uses `react-force-graph-2d`. |
| `Timeline` | [`frontend/src/components/Timeline.jsx`](../../frontend/src/components/Timeline.jsx) | Clustered status-change events over the past N hours. Engineer only. |

## System chrome

| Component | File | Role |
|-----------|------|------|
| `ShortcutsOverlay` | [`frontend/src/components/ShortcutsOverlay.jsx`](../../frontend/src/components/ShortcutsOverlay.jsx) | Modal with keyboard-shortcut map. Toggled with `?`. |
| `ReloadPrompt` | [`frontend/src/components/ReloadPrompt.jsx`](../../frontend/src/components/ReloadPrompt.jsx) | PWA update toast: "a new version is available, reload?". Driven by `virtual:pwa-register/react`. |

## Mode-gated rendering

```text
Engineer mode:
  StatusBanner → IncidentSection → ServiceGrid → MaintenanceBanner → Timeline

Executive mode:
  StatusBanner → IncidentSection → CategorySummary → MaintenanceBanner

Global:  Header (ViewToggle + Dependencies + ?) → ErrorBanner → [view] → footer
Overlays (both modes): ServiceDetail drawer, ShortcutsOverlay, ReloadPrompt
Overlays (engineer only): DependencyGraph
```

## Data contract the components depend on

| Component consumes | Shape |
|---|---|
| `services` poll → `/api/services` | `{ services: [...], total, healthy_count, degraded_count, outage_count, unknown_count }`. Each service has `id`, `display_name`, `category`, `current_status`, `current_status_detail`, `poll_type`, `poller_health`, `last_failure_reason`, `last_polled_at`, `tier`, `pending_status`, `pending_status_count`, `pending_status_since`. |
| `summary` poll → `/api/summary` | `{ overall_status, active_incidents: [...], maintenance_windows: [...] }` |
| `timeline` poll → `/api/timeline/clustered` | `[{ cluster_id, title, events: [...], severity, started_at, ... }]` |
| `sla` poll → `/api/services/sla` | `{ services: { [id]: { uptime_24h, uptime_7d, uptime_30d } } }` |
| `uptime` poll → `/api/services/uptime` | Per-service, per-day worst status for the last 7 days. |

Claude Design does not need to touch the API contract. Every redesign proposal stays inside these shapes.
