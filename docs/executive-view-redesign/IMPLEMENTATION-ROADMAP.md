# Executive-View Redesign — Implementation Roadmap

## Architecture

### System Overview

```
                      [App.jsx]
                         |
                 ViewContext (existing)
                  /                \
         view=engineer          view=executive   <-- this branch is the redesign
                \                    |
         ServiceGrid +         [ExecutiveView.jsx]   (new — frontend/src/views/)
         Timeline + ...               |
                             use-executive-data.js   (new — frontend/src/hooks/)
                                      |
              +--------+---------+-----------+-------------+
              |        |         |           |             |
     ExecutiveStatus  ExecutiveKpi  ExecutiveTrend  ExecutiveImpact
         Panel         Tiles          Strip            List
              |        |         |           |             |
              +--------+---------+-----------+-------------+
                                      |
                              existing FastAPI:
                              /api/summary
                              /api/services
                              /api/services/sla
                              /api/services/sla/history?days=30
```

The redesign is a single new branch hanging off `ViewContext`. The existing `use-polling` hook is reused; `use-executive-data.js` is a thin composition layer that calls four `usePolling` instances and memoizes derived KPIs (incident count, degraded-vendor count, weighted SLA, sorted impact rows, normalized 30-day series).

### File Structure

```
frontend/
  src/
    views/
      ExecutiveView.jsx                     (new — top-level shell for view === "executive")
    components/
      executive/
        ExecutiveStatusPanel.jsx            (new — primary status-summary panel)
        ExecutiveKpiTiles.jsx               (new — 3 KPI tiles row)
        ExecutiveTrendStrip.jsx             (new — 30-day uptime sparkline)
        ExecutiveImpactList.jsx             (new — sorted impact list)
      CategorySummary.jsx                   (existing — removed from render path in Phase 2; file deleted)
    hooks/
      use-executive-data.js                 (new — composes /api/summary + /api/services + SLA + SLA history)
      use-polling.js                        (existing — reused, not modified)
    lib/
      executive-tokens.js                   (new — typography + spacing constants consumed by executive components only)
      constants.js                          (existing — extended with EXEC_SLA_TARGET, EXEC_IMPACT_LIMIT)
    styles/
      index.css                             (existing — extended @theme block with alarm + display tokens)
  docs/executive-view-redesign/
    screenshots/
      exec-operational.png                  (captured in Phase 3)
      exec-major.png                        (captured in Phase 3)
```

### Data Model

No database migrations. All data is read-only from existing endpoints. Derived shapes (computed inside `use-executive-data.js`):

```js
// ExecutiveData — the shape returned by use-executive-data.js
{
  // Headline
  overallStatus:    "operational" | "degraded" | "partial_outage" | "major_outage" | "unknown",
  headline:         "All Systems Operational" | "Active Incident" | "N Active Incidents",
  incidentsOpen:    number,              // active_incidents.length from /api/summary
  vendorsDegraded:  number,              // services where effectiveStatus !== "operational" && !== "unknown"
  totalMonitored:   number,              // total_services - unknown_count
  slaTarget:        number,              // EXEC_SLA_TARGET constant, default 99.9
  slaObserved:      number,              // weighted mean of uptime_30d across services with non-null SLA
  slaDeltaBps:      number,              // (slaObserved - slaTarget) in basis points; negative => under target

  // Sorted impact list, worst first, operational services excluded
  impact: [
    {
      id:             string,            // service id
      label:          string,            // service name
      category:       string,            // category label
      status:         "degraded" | "partial_outage" | "major_outage" | "unknown",
      isPollerBroken: boolean,
      impactLine:     string,            // templated from /api/summary active_incidents.impact, fallback to status label
      sinceIso:       string | null,     // ISO timestamp when status last changed, if available
    },
    // ...
  ],

  // 30-day aggregate trend: daily mean uptime across monitored services, oldest first
  trend: [
    { date: "YYYY-MM-DD", uptimePct: number, anyDegraded: boolean },
    // ... 30 entries
  ],

  // Fetch metadata
  lastUpdatedMs: number | null,
  isStale:       boolean,
  error:         Error | null,
}
```

All five fetches are read-only. No writes. No new tables.

### Type Definitions

Project uses JSX + JSDoc, not TypeScript. Provide JSDoc typedefs at the top of `use-executive-data.js` so editors and `eslint-plugin-react-hooks` infer props correctly. Minimum required:

```js
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
 * @property {number} uptimePct
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
 * @property {number} slaObserved
 * @property {number} slaDeltaBps
 * @property {ImpactRow[]} impact
 * @property {TrendPoint[]} trend
 * @property {number|null} lastUpdatedMs
 * @property {boolean} isStale
 * @property {Error|null} error
 */
```

### API Contracts

**External APIs:**

| Service | Endpoint | Method | Auth | Rate Limit | Pagination | Purpose |
|---------|----------|--------|------|------------|------------|---------|
| Pulse backend | `/api/summary` | GET | none (internal network boundary) | n/a — local | none | overall_status, active_incidents[], counts |
| Pulse backend | `/api/services` | GET | none | n/a — local | none | per-service status, poller_health, category |
| Pulse backend | `/api/services/sla` | GET | none | n/a — local | none | uptime_24h / uptime_7d / uptime_30d per service |
| Pulse backend | `/api/services/sla/history?days=30` | GET | none | n/a — local | none | daily uptime points per service, 30-day window |

No external third-party APIs. No auth headers from the frontend. The backend is already polling the vendor status pages; the redesign is strictly a read-side refactor.

### Dependencies

No installs required. Every package needed is already pinned in `frontend/package.json`:

```bash
# Confirm the pinned versions are present (read-only check — do not reinstall)
cd frontend && npm ls recharts lucide-react @tailwindcss/vite tailwindcss date-fns
```

Expected (already installed): `recharts@^3.8.1`, `lucide-react@^1.8.0`, `@tailwindcss/vite@^4.2.2`, `tailwindcss@^4.2.2`, `date-fns@^4.1.0`.

## Scope Boundaries

**In scope:**
- New `ExecutiveView.jsx` shell + 4 new components under `components/executive/`
- New `use-executive-data.js` hook
- Extensions to `styles/index.css` `@theme` block (tokens)
- Extensions to `lib/constants.js` (new exec-only constants)
- Integration into `App.jsx` under the `view === "executive"` branch
- Retirement of `CategorySummary.jsx` from the executive render path, deletion of the component file, and removal of its import from `App.jsx`
- Screenshot capture for the pitch deck

**Out of scope:**
- Engineer view (`ServiceGrid`, `ServiceDetail`, `DependencyGraph`, `Timeline`, `ServiceTile`)
- Backend endpoints, pollers, alerting, observability, SQLite, launchd, Caddy, Litestream
- `ViewContext` itself — reused as-is
- PWA manifest, service worker, reload prompt
- Any work gated behind `WEBHOOKS_ENABLED` or `SLACK_ACK_ENABLED`

**Deferred:**
- Runtime-configurable `EXEC_SLA_TARGET` (env or admin endpoint) → deferred to a post-handoff phase; constant is sufficient for v1
- Per-category drilldown in the impact list → engineer view already covers this; revisit only if conference-room usage surfaces the need
- Animations beyond CSS transitions — `prefers-reduced-motion` is already honored globally; no new motion in this redesign

## Security & Credentials

- Credential storage: not applicable — all endpoints are read-only and the internal network is the security boundary per root `CLAUDE.md`.
- Data boundaries: nothing leaves the browser except the existing same-origin XHRs.
- Encryption: n/a — same-origin HTTPS once Caddy terminates TLS in production; not a concern for this feature.
- Token rotation: n/a — no admin endpoints touched.

---

## Phase 0: Foundation — tokens, data hook, view shell (Week 1, ~3–4 h)

**Objective:** Land the non-UI scaffolding — design tokens, the executive data hook, the empty `ExecutiveView.jsx` shell, and the `App.jsx` wire-up that swaps `CategorySummary` for `ExecutiveView` when `view === "executive"`. No new visible UI components render yet; the shell renders a single placeholder `<p>` so the branch is exercised end-to-end.

**Tasks:**
1. Extend `frontend/src/styles/index.css` `@theme` block with `--color-accent-alarm: #ef4444`, `--color-surface-elev-1: #0f172a`, `--color-surface-elev-2: #1b2436`, `--color-text-display: #f8fafc`, `--color-text-dim: #64748b`, and type-scale vars `--text-body: 0.875rem`, `--text-lede: 1.75rem`, `--text-h2: 3.5rem`, `--text-display: 7rem` — Acceptance: `cd frontend && npm run build` succeeds and `grep -c "accent-alarm" dist/assets/*.css` ≥ 1.
2. Create `frontend/src/lib/executive-tokens.js` exporting `EXEC_SLA_TARGET = 99.9`, `EXEC_IMPACT_LIMIT = 8`, and helpers `formatSlaPct(n)`, `formatDeltaBps(n)` — Acceptance: `cd frontend && node -e "import('./src/lib/executive-tokens.js').then(m => console.log(m.EXEC_SLA_TARGET))"` prints `99.9`.
3. Create `frontend/src/hooks/use-executive-data.js` composing the four endpoints and returning the `ExecutiveData` shape from the type defs above; mean-weighted `slaObserved` skips services with null uptime_30d — Acceptance: a temporary `console.log` inside `ExecutiveView` logs a fully-populated `ExecutiveData` object at `localhost:5173` with `SEED_DEMO_DATA=true`.
4. Create `frontend/src/views/ExecutiveView.jsx` as a shell that calls `useExecutiveData()` and renders a single `<p data-testid="exec-shell">exec shell ready</p>` — Acceptance: rendering the app with `view === "executive"` shows exactly that paragraph.
5. Rewire `frontend/src/App.jsx` so the branch at `App.jsx:163-165` renders `<ExecutiveView />` instead of `<CategorySummary />`; keep the `CategorySummary` import commented with `// retired in Phase 2` so Phase 2 has a deletion target — Acceptance: toggling the view selector shows the exec shell string; engineer view is unchanged.

**Verification checklist:**
- [ ] `cd frontend && npm run build` — exits 0
- [ ] `cd frontend && npm run lint` — exits 0 with no new warnings
- [ ] `cd frontend && npm run dev` then load `http://localhost:5173` in Executive view → see `exec shell ready`
- [ ] Engineer view renders the existing grid unchanged

**Risks:**
- Tailwind 4 `@theme` keys collide with existing token names: Mitigation — prefix new tokens with `accent-alarm` and `surface-elev-*`, verify via build → Fallback: alias new tokens under `--color-exec-*` namespace.
- `use-executive-data.js` re-renders every second due to `setStaleTick` in `App.jsx`: Mitigation — memoize the returned shape with `useMemo` keyed on the raw fetch payloads → Fallback: skip the memo and tolerate re-renders since computation is O(n) over ~30 services.
- `SEED_DEMO_DATA` not enabled during dev so SLA history is empty: Mitigation — set `SEED_DEMO_DATA=true` in `backend/.env` for local work, note it in the kickoff → Fallback: hardcode a fixture in `use-executive-data.js` behind a dev-only flag, delete before Phase 2.

**Parallel Dispatch Proposal (≥3 disjoint tasks):**
- Dispatchable in parallel: Task 1 (tokens in `index.css`), Task 2 (constants in `executive-tokens.js`), Task 3 (`use-executive-data.js`). They touch three unrelated files with no data or code dependency on each other.
- Subagent type: `general-purpose`
- Rationale: each task is a single-file write with verifiable acceptance; serialization buys nothing. Task 4 (`ExecutiveView.jsx`) and Task 5 (`App.jsx`) run sequentially after because they depend on 1–3.

**Phase-end review:** Run `/ultrareview`. Address all findings before marking the phase complete.

---

## Phase 1: Core UI — status panel, KPI tiles, impact list (Week 1, ~6–8 h)

**Objective:** Ship the three primary UI surfaces that comprise the conference-room read. Each component is a pure function of `ExecutiveData`; none fetches its own data. The trend strip is deferred to Phase 2 so this phase stays focused on the 3-surface ceiling mandated for a first UI phase.

**Tasks:**
1. Build `frontend/src/components/executive/ExecutiveStatusPanel.jsx` — full-width primary panel, 112 px display type for the headline ("All Systems Operational" / "N Active Incidents"), status chip left-aligned, timestamp in monospace bottom-right. Background uses `--color-accent-alarm` **only** when `overallStatus ∈ {degraded, partial_outage, major_outage}`; otherwise `--color-surface-elev-1` — Acceptance: screenshot in Executive view with seed data shows the headline at the 112 px display scale and the alarm-red background flips on/off as status changes via `POST /api/admin/status`.
2. Build `frontend/src/components/executive/ExecutiveKpiTiles.jsx` — three equal-width tiles: (a) "Incidents open", (b) "Vendors degraded", (c) "SLA (30d) vs target". Tile numbers render at the 56 px `--text-h2` scale; labels at 14 px `--text-body`. Tile (c) shows the observed % with a ±bps delta line beneath; delta uses `--color-accent-alarm` only when negative — Acceptance: three tiles visible in 12-col grid layout at ≥1920×1080; numbers update live on a 30 s cadence; delta arrow flips color correctly when the observed SLA dips below target.
3. Build `frontend/src/components/executive/ExecutiveImpactList.jsx` — sorted list capped at `EXEC_IMPACT_LIMIT` rows. Sort by severity rank desc, then `sinceIso` desc. Each row: service label (28 px lede weight 600), status chip, impact line (14 px body), "since" duration in monospace. Operational services never appear. If `impact.length === 0`, render a single "No active impact" row in muted text — Acceptance: with seed data and at least two non-operational services, the worst status appears first; empty state renders when all services are operational.
4. Wire all three components into `frontend/src/views/ExecutiveView.jsx` using a 12-col CSS grid: panel spans 12, tiles span 12 (three equal cells), impact spans 12. Remove the Phase-0 placeholder `<p>` — Acceptance: Executive view renders the panel + 3 tiles + impact list stacked vertically with generous whitespace (≥64 px between sections).

**Verification checklist:**
- [ ] `cd frontend && npm run build` — exits 0
- [ ] `cd frontend && npm run lint` — exits 0
- [ ] `cd frontend && npm run dev` then toggle between operational and major_outage via `POST /api/admin/status`; the panel background flips between `--color-surface-elev-1` and `--color-accent-alarm`
- [ ] All visible text uses only the scale vars `--text-body / --text-lede / --text-h2 / --text-display` — verify by searching the new component files: `grep -rE "text-(xs|sm|base|lg|xl|2xl|3xl|4xl)" frontend/src/components/executive/` returns zero matches
- [ ] No hex literals in the new component files: `grep -rE "#[0-9a-fA-F]{3,6}" frontend/src/components/executive/` returns zero matches

**Risks:**
- 112 px display type overflows on 16:9 monitors below 1440 px width: Mitigation — wrap headline in `text-balance` and cap at `min(7rem, 12vw)` with `clamp()` → Fallback: step down to 96 px on `< 1600px` via a responsive token.
- Tile grid collapses awkwardly on 4:3 NOC screens: Mitigation — use CSS grid with `grid-template-columns: repeat(3, minmax(0, 1fr))` and a 1024 px breakpoint to stack 1-per-row → Fallback: explicit media-query override.
- Impact list "since" duration re-renders too aggressively: Mitigation — compute once per polling cycle inside `use-executive-data.js`, not on every `setStaleTick` → Fallback: accept the per-second re-render since row count ≤8.

**Parallel Dispatch Proposal (≥3 disjoint tasks):**
- Dispatchable in parallel: Task 1 (`ExecutiveStatusPanel.jsx`), Task 2 (`ExecutiveKpiTiles.jsx`), Task 3 (`ExecutiveImpactList.jsx`). Three separate files, each a pure function of the already-delivered `ExecutiveData` shape — no cross-component state.
- Subagent type: `general-purpose`
- Rationale: each component is single-file and contract-bound by the typedef from Phase 0. The integration step (Task 4) waits for all three, then stitches into `ExecutiveView.jsx`.

**Phase-end review:** Run `/ultrareview`. Address all findings before marking the phase complete.

---

## Phase 2: Trend strip + integration cleanup (Week 2, ~3–4 h)

**Objective:** Add the 30-day trend strip beneath the KPI tiles, delete the retired `CategorySummary` component and its import, and confirm the four-region layout (panel → tiles → trend → impact) reads cleanly from a conference-room distance.

**Tasks:**
1. Build `frontend/src/components/executive/ExecutiveTrendStrip.jsx` — full-width strip rendering `trend[]` via a recharts `<AreaChart>` with a single `<Area dataKey="uptimePct">` filled in `--color-surface-elev-2`, axis hidden, tooltip showing date + uptime %. Any day with `anyDegraded` true gets a vertical `<ReferenceLine>` marker in `--color-accent-alarm` — Acceptance: strip renders 30 data points in the correct chronological order (oldest left, newest right); degraded days show alarm-red marker; hover tooltip appears with date and %.
2. Remove the `CategorySummary` import + the `// retired in Phase 2` comment from `frontend/src/App.jsx`; delete `frontend/src/components/CategorySummary.jsx` — Acceptance: `grep -r "CategorySummary" frontend/src` returns zero matches; engineer view still builds and renders.
3. Insert `<ExecutiveTrendStrip />` into `frontend/src/views/ExecutiveView.jsx` between the KPI tiles and the impact list, spanning 12 columns, with ≥64 px margin above and below — Acceptance: Executive view at 1920×1080 shows panel / tiles / strip / impact stacked with visible breathing room between sections.

**Verification checklist:**
- [ ] `cd frontend && npm run build` — exits 0
- [ ] `cd frontend && npm run lint` — exits 0
- [ ] `grep -r "CategorySummary" frontend/src` → zero matches
- [ ] Strip renders 30 points in dev mode with seeded SLA history; degraded days marked
- [ ] Toggle to Engineer view → grid + timeline + drawer unchanged

**Risks:**
- Backend returns fewer than 30 days of history on a fresh DB: Mitigation — front-pad missing days with `null` gaps that recharts renders as broken line segments → Fallback: show a muted "Gathering history — N of 30 days available" caption for the first week.
- recharts bundle weight spike from adding `<AreaChart>`: Mitigation — recharts is already bundled for `SlaChart`; reuse the same import path → Fallback: if the bundle grows > 10 KB, swap `<AreaChart>` for a hand-drawn SVG polyline.

**Parallel Dispatch Proposal:** not applicable — only two disjoint tasks (strip + deletion) and they must land in the same commit to keep `grep` verification meaningful.

**Phase-end review:** Run `/ultrareview`. Address all findings before marking the phase complete.

---

## Phase 3: Accessibility, responsive, screenshot capture (Week 2, ~3 h)

**Objective:** Prove the redesign reads at 3 m, works with a keyboard, announces status changes to screen readers, and capture the two screenshots the pitch deck and case study need.

**Tasks:**
1. Add a screen-reader-only `<div role="status" aria-live="polite" aria-atomic="true">` inside `ExecutiveView.jsx` that announces `"{incidentsOpen} incidents open, {vendorsDegraded} vendors degraded, SLA {slaObserved.toFixed(2)} percent"` whenever `overallStatus` changes — Acceptance: VoiceOver (macOS) or NVDA reads the string once per real status transition, not on every poll.
2. Verify keyboard tab order is: view toggle → trend strip (if focusable) → impact list rows → help (`?`). Add `tabIndex={0}` to impact rows so keyboard users can focus each entry — Acceptance: pressing Tab from the header reaches each impact row in visual order; focus-visible outlines use the existing `--color-accent` ring from `index.css`.
3. Add a 1024 px breakpoint in `ExecutiveView.jsx` that stacks the KPI tiles one-per-row; verify the layout at 1920×1080 (boardroom 16:9), 1280×1024 (4:3 NOC display), and 1080×1920 (portrait wall) — Acceptance: each viewport shows the four regions without horizontal scroll; the headline never wraps to more than two lines.
4. Capture `docs/executive-view-redesign/screenshots/exec-operational.png` at 1920×1080 with all services healthy, and `docs/executive-view-redesign/screenshots/exec-major.png` with at least one service in `major_outage` — Acceptance: both files exist on disk, ≥1920 px wide, ready for embedding in the pitch deck (Session 3) and the case study (Session 4).
5. Run `/ultrareview` against the full bundle — Acceptance: no blocking findings; all minor findings either fixed or explicitly deferred.

**Verification checklist:**
- [ ] `cd frontend && npm run build` — exits 0
- [ ] `cd frontend && npm run lint` — exits 0
- [ ] Tab through the Executive view from the header; focus ring is visible on every stop
- [ ] VoiceOver announces the live-region string once per real status change
- [ ] Both screenshot files present under `docs/executive-view-redesign/screenshots/`
- [ ] `/ultrareview` run on `git diff main` — findings addressed

**Risks:**
- `aria-live` spams announcements on every 30 s poll because equality check is reference-based: Mitigation — compare the previous `overallStatus` value via `useRef` and only update the live region text when it actually changes → Fallback: debounce to 10 s.
- Portrait NOC viewport breaks the 12-col grid: Mitigation — swap to a 4-col grid below 768 px width → Fallback: hide the trend strip on portrait and retain panel + tiles + impact only.
- `/ultrareview` surfaces new requirements: Mitigation — any finding that expands scope becomes a Phase 4 ticket rather than blocking this phase → Fallback: promote the finding into Session 2's architecture-diagram notes if it's structural.

**Parallel Dispatch Proposal:** not applicable — Tasks 1–3 are a sequential a11y/responsive sweep; Task 4 depends on Tasks 1–3 being visually final; Task 5 is the phase gate.

**Phase-end review:** Run `/ultrareview`. Address all findings before marking the phase complete.
