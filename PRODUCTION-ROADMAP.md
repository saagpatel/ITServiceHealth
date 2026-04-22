# IT Service Health Dashboard — Production Roadmap

> **This is the active roadmap.** It supersedes `IMPLEMENTATION-ROADMAP.md` (which documents the v1 build that is already complete). All new work tracks against the phases below.

## Status

- **v1 (demo) — SHIPPED.** Polling, normalization, change detection, Slack alerting, React UI, dependency graph, timeline, SLA tracking, incident clustering, auto reports — all implemented and running. See `IMPLEMENTATION-ROADMAP.md` for the historical spec.
- **v2 (production-ready) — SHIPPED.** Phases 0–6 complete, plus Phase 2B (Slack ack) and Phase 7 inbound Statuspage webhook — both feature-gated off by default until a public reachability path (Cloudflare Tunnel / Caddy allowlist) is in place. 276 tests passing. See phase sections below for deferred items still open.

## Guiding principle

The jump from demo to production isn't about features — it's about **honesty under failure**. A mature status dashboard:
- Knows when it is blind and says so (never renders `operational` when the poller is broken).
- Doesn't page on vendor flaps (consecutive-threshold, minimum state duration, dedup by vendor incident ID).
- Surfaces its own health alongside the services it watches (self-monitoring, dead-man's switch).
- Is trusted by leadership (severity-sorted, accessible, clearly labeled stale data).

Sources: Google SRE Workbook (Alerting on SLOs, Postmortem Culture, On-Call), Atlassian Statuspage developer docs, hynek/stamina, mardiros/purgatory, Litestream, Gatus, Datadog / Grafana / PagerDuty / incident.io engineering blogs.

---

## Phase 0 — Stop the bleeding (week 1) — COMPLETE

Critical correctness, security, and validation fixes found in the deep code audit. No feature work — only surgical fixes.

### Security & auth
- [x] `backend/app/router_admin.py` — Bearer-token auth on `POST /api/admin/status`. Token from `ADMIN_API_TOKEN` env var. 401 on missing, 403 on mismatch, 503 when unset (fail closed).
- [x] Admin request body — Pydantic model with `ServiceStatus` enum field; `reason` required (3–500 chars).
- [x] Validate `service_id` exists in DB before status insert (404 if not found). _(already present pre-Phase 0)_
- [x] Audit fields on `status_events` (migration 0004): `updated_by`, `reason`, `client_ip`. Written on manual updates.
- [x] `backend/app/main.py:24` — CORS origins from `CORS_ORIGINS` env var (CSV), not hardcoded `localhost:5173`.

### Correctness bugs (from audit, verified against real code)

Several audit claims were false positives on verification — noted here so future sessions don't re-litigate:

- ~~`change_detector.py:82` missing commit on UNKNOWN~~ — FALSE POSITIVE. Batched `db.commit()` at line 139 covers all paths inside the write_lock.
- ~~`change_detector.py:132` detail update without timestamp~~ — FALSE POSITIVE. `last_status_change_at` correctly tracks status (enum) changes, not detail text changes.
- ~~`reports.py:71` inverted recovery logic~~ — FALSE POSITIVE. Walks events DESC looking for a recovery (`new_status == operational` excluding boot warmup), then includes predecessor events. Logic is correct.
- ~~`alerting/engine.py:64` nested SELECT without LIMIT~~ — FALSE POSITIVE. `ORDER BY created_at DESC LIMIT 1` is already present.
- ~~`dependencies/graph.py` cycle detection~~ — FALSE POSITIVE. `get_downstream`/`get_upstream` do single SQL queries, not recursion. Revisit if recursive traversal is added later.

**Real fixes to apply in Phase 0:**
- [x] `backend/app/alerting/slack.py` — Hardened `Retry-After` parsing via `_parse_retry_after`: handles int, HTTP-date (RFC 7231), negative/zero/garbage values; capped at 60s max.

### Config validation at startup (fail fast)
- [x] `backend/app/config.py` — `poll_interval_seconds: int = Field(gt=0, le=3600)`.
- [x] `backend/app/config.py` — `slack_webhook_url: HttpUrl | None` plus `port` bounds and `log_level` enum validation.
- [x] `backend/app/seed.py` — `load_dependencies(known_service_ids=...)` cross-validates every upstream and downstream against services.yaml; raises ValueError listing all offending edges.
- [x] `backend/app/main.py` lifespan — Pass `known_service_ids` to `load_dependencies`; Pydantic validation runs at `Settings()` instantiation so the app refuses to start on bad env.

**Exit criteria:** all unit tests pass (129/129 ✓), manual admin endpoint requires a token, app refuses to start on malformed config.

---

## Phase 1 — Vendor resilience (week 2) — COMPLETE (UI visuals deferred to Phase 5)

Current pollers have no retry/backoff/circuit-breaker logic. Fix the resilience layer so one vendor flapping can't take down the tool or trigger IP bans.

### Libraries
- **`stamina`** (hynek) for retries — exponential backoff with full jitter, opinionated defaults, Prometheus/structlog hooks.
- **`purgatory`** for circuit breakers — async context-manager form, one breaker *per vendor host* (shared across services on the same status infra).

### Tasks
- [x] Add `stamina` + `purgatory` (+ `respx` for tests) to `requirements.txt`.
- [x] `backend/app/poller/resilience.py` — `resilient_fetch(client, url)` wraps every outbound poll with stamina retries + per-host purgatory breaker. Shared `describe_fetch_error` returns (user_detail, mechanical_reason) tuples so every poller writes consistent failure strings.
- [x] Circuit breaker per unique host, `threshold=3`, `ttl=300s` (configurable via `BREAKER_THRESHOLD`/`BREAKER_TTL_SECONDS`).
- [x] `backend/app/main.py` lifespan — shared `httpx.AsyncClient` now configured with `Limits(max_connections=20, max_keepalive_connections=10, max_connections_per_host=1, keepalive_expiry=30)` and `Timeout(10.0, connect=5.0, read=10.0, write=5.0, pool=2.0)`. Breakers initialised from settings at startup.
- [x] Retry only on 408/429/5xx + network errors (via `TransientHTTPError` wrapper). 404 raises immediately with `http_404` failure reason — no retries, no breaker increment for hard HTTP errors.

### Per-service health tracking (schema change)
Migration `0005_poller_health.sql` adds `consecutive_failures`, `last_success_at`, `last_failure_reason`, `poller_health` to the `services` table plus an index on `poller_health`.

- [x] `detect_changes` now returns `(status_changes, health_changes)` and runs a pure state machine (`_compute_new_health`) to derive the new health value. Success clears; 1–2 failures = `degraded`; `poller_failure_threshold` (default 3) consecutive failures = `broken`.
- [x] Scheduler fans out both lists: vendor outages to `process_changes`, poller-health transitions to `process_poller_health_changes` on a dedicated webhook (`POLLER_HEALTH_SLACK_WEBHOOK_URL`, falls back to main webhook with a "poller-health" tag).
- [x] `build_poller_health_alert` renders distinct `🔧 Poller BROKEN` / `✅ Poller RECOVERED` messages so responders never confuse them with vendor alerts.
- [x] API responses (`/api/services`, `/api/services/{id}`) now surface `consecutive_failures`, `last_success_at`, `last_failure_reason`, `poller_health` to the frontend.
- [ ] UI tile visual "unknown" state for `poller_health != 'healthy'` — **deferred to Phase 5** (UX production). Data is already on the wire.

### Normalizer hardening
- [x] `normalize_statuspage_component` and `normalize_statuspage_indicator` log WARNING with the unmapped value when returning UNKNOWN. Prometheus counter hookup deferred to Phase 3 observability.

### Test coverage added
- `tests/test_resilience.py` — 16 tests covering retries, breaker open/close, host isolation, TTL recovery, error description.
- `tests/test_change_detector.py` — 7 new tests for poller-health state machine + transitions.
- `tests/test_poller_integration.py` — 12 respx-mocked tests exercising each vendor poller's happy + failure paths.

**Exit criteria met:** simulated vendor 500s retry then surface `transient_http_500` without blowing up alerts; one host failing does not affect others (`test_breaker_isolates_hosts`); `poller_broken` state is recorded distinct from `operational` in the DB and exposed via the API (`test_three_failures_flip_to_broken`). 164 tests passing.

---

## Phase 2 — Alert quality (week 3) — COMPLETE (ack flow deferred)

Alert fatigue is the #1 killer of status dashboards. Current pipeline fires on every state change with no dedup, flap suppression, or correlation.

### Flap suppression + hysteresis (Gatus model)
- [x] Require N consecutive failures (default 3) before firing an alert. `ALERT_CONFIRM_THRESHOLD_POLLS` configurable.
- [x] Require M consecutive successes (default 2) before clearing. `ALERT_RECOVERY_THRESHOLD_POLLS` configurable.
- [x] Enforce minimum state duration (default 10 min / 600s) for worsening transitions only. `ALERT_MIN_STATE_DURATION_SECONDS`.
- [x] DB columns `pending_status`, `pending_status_count`, `pending_status_since` on `services` (migration 0006).
- [x] Pure `_update_pending()` state machine — 9 unit tests + 4 integration tests cover single blips, confirmed transitions, target changes mid-stream, and recovery threshold.
- [ ] "Unstable" UI badge for actively-flapping services — **deferred to Phase 5** (UX). Data exposed via the `pending_*` columns.

### Dedup
- [x] `alert_sent_log` table keyed on `dedup_key = vendor:{service_id}:{vendor_incident_id}` or fallback `fallback:{service_id}:{status}:{day}`.
- [x] Never dedups on message text. `alert_dedup_window_seconds` configurable (default 24h).
- [x] Recoveries to `operational` bypass dedup — operators always want "it's back" even if they just saw the outage.
- [x] Suppressed alerts still recorded (with `suppressed_by` reason code) so "why didn't we alert?" is auditable.
- [ ] `vendor_incident_id` extraction from Statuspage — **deferred** follow-up; fallback day-bucket dedup works today.

### Severity routing (config-driven)
- [x] `tier` (`critical | important | informational`) + `slack_channel_override` added to `services.yaml`, `ServiceConfig`, and the DB via migration 0006.
- [x] `okta`, `duo`, `slack` tagged `critical`; everything else defaults to `important` so operators explicitly elect services into the `@here` tier.
- [x] `route_status_change()` applies routing:
  - `critical` → Slack + `<!here>` mention
  - `important` → Slack, no mention
  - `informational` → dashboard only, no Slack
- [ ] Per-service `slack_channel_override` → distinct webhook — **deferred**; field exists but routing only uses main webhook today.

### Dependency correlation
- [x] `find_aggregation_candidates()` groups downstream outages under their upstream when ≥ `dependency_correlation_threshold` (default 3) dependents flip non-operational in the same poll cycle.
- [x] `build_aggregated_upstream_alert()` renders one Slack message citing up to 20 affected dependents (plus "…and N more").
- [x] Individual dependent alerts are suppressed (`aggregated_under_upstream`) when rolled into the parent. No 20-alert thundering herd.

### Maintenance windows (first-class)
- [x] Using the existing `scheduled_maintenances` table (from migration 0001) — no new table needed.
- [x] `is_in_maintenance_window()` normalizes both sides through SQLite's `datetime()` to handle vendor ISO and space-separated timestamps.
- [x] Alerts during active windows are recorded with `suppressed_by='maintenance_window'` but don't fire. State transitions still captured.

### Ack flow — COMPLETE (Phase 2B, feature-gated off by default)
- [x] `POST /api/slack/interactivity` — Slack v0 signing-secret verification (`v0:{ts}:{body}` HMAC-SHA256), replay protection (5-min window), parses `application/x-www-form-urlencoded` payload field.
- [x] `block_actions` with `action_id == "ack_alert"` → sets `acknowledged_at` + `acknowledged_by` on most-recent unresolved `alert_sent_log` row.
- [x] POSTs to `response_url` with `replace_original: true` + appended `✓ Acknowledged by @username at HH:MM UTC` context block.
- [x] `build_slack_alert` + `build_aggregated_upstream_alert` append an Acknowledge button (`style: primary`) only when `SLACK_ACK_ENABLED=true` and a `dedup_key` is provided. Disabled path is byte-for-byte unchanged.
- [x] Feature-gated: `SLACK_ACK_ENABLED=false` (default) → 404; `SLACK_SIGNING_SECRET` unset → 503.
- [x] Requires public reachability (Cloudflare Tunnel, exposed ingress) — gate off until reachability is confirmed.

### Test coverage added
- `tests/test_change_detector.py` — 13 new tests (9 state-machine + 4 integration).
- `tests/test_routing.py` — 23 new tests spanning dedup-key construction, maintenance detection, recent-alert checks, every routing suppression path, `record_alert`, and aggregation candidates.

**Exit criteria met:**
- Single-poll blip fires zero alerts (`test_single_blip_produces_zero_alerts`).
- Three consecutive polls confirm a real change (`test_three_polls_confirm_status_change`).
- Dedup window blocks repeats, recoveries bypass (`test_recent_dedup_suppresses`, `test_recovery_bypasses_dedup`).
- Upstream down + ≥3 declared dependents = 1 aggregated alert (`test_aggregates_when_threshold_met`).
- Maintenance window fully suppresses alerts (`test_maintenance_window_suppresses`).
- Informational-tier services are never Slack-paged (`test_informational_tier_is_suppressed`).

200 tests passing.

---

## Phase 3 — Observability (week 4) — COMPLETE

If the app goes down, nobody knows. Fix meta-monitoring.

### Structured logging
- [x] `app/logging_config.py` configures structlog (v25) with `contextvars.merge_contextvars` so every log line (native structlog **and** stdlib `logging.getLogger`) carries whatever's currently bound.
- [x] `poll_cycle_id` bound at the top of `run_poll_cycle` and cleared in `finally`. Operators grep the JSON log for one cycle ID to see every effect.
- [x] JSON renderer in prod (`LOG_JSON=true`), pretty console in dev. Third-party loggers (httpx, apscheduler) go through the same formatter.
- [ ] `QueueHandler`/`QueueListener` moving log I/O off the event loop — **deferred**; current volume is fine with direct stderr, revisit if log write ever blocks.

### Prometheus metrics at `/metrics`
- [x] `poll_duration_seconds{poll_type}` — histogram with buckets `[0.1, 0.25, 0.5, 1, 2, 5, 10, 30]`. Labeled by `poll_type` rather than `service` because batch pollers share one HTTP fetch across several services (truthful cardinality).
- [x] `poll_total{service, outcome}` — counter. Outcome ∈ `ok | timeout | http_5xx | http_4xx | circuit_open | request_error | parse_error | other` via `outcome_from_failure_reason()`.
- [x] `service_status{service}` — gauge (0=operational, 1=degraded, 2=partial, 3=major, 4=unknown). Updated on confirmed promotions.
- [x] `poller_health_state{service}` — gauge (0=healthy, 1=degraded, 2=broken).
- [x] `alerts_sent_total{kind, severity}` and `alerts_suppressed_total{kind, reason}` — counters covering both fired and suppressed alerts for alert-hygiene dashboards.
- [x] `scheduler_last_heartbeat_seconds` — gauge refreshed every 5s by a dedicated APScheduler job.
- [x] `circuit_breaker_state{host}` — gauge driven by purgatory's event listener (closed=0, opened=1, half_opened=2).
- [x] `poll_cycles_total{outcome}` — counter.
- [x] `/metrics` endpoint mounted in main.py (plain Prometheus text).

### Dead-man's switch
- [x] Dedicated heartbeat APScheduler job runs every `HEARTBEAT_INTERVAL_SECONDS` (default 30s). In-memory `_last_heartbeat_monotonic` + Prometheus gauge.
- [x] If `HEALTHCHECK_PING_URL` is set, the heartbeat GETs it with a short-lived httpx client. Failures are logged, never raised.
- [x] `/healthz` returns **200** when heartbeat is fresh, **503** when stale past `HEARTBEAT_STALE_AFTER_SECONDS` (default 120s). Launchd + Healthchecks.io can both key off this.

### Sentry (free tier)
- [x] `sentry-sdk[fastapi]` init in lifespan — no-op when `SENTRY_DSN` is unset.
- [x] `before_send` scrubs Slack webhook URLs, Bearer tokens, and `Authorization` headers from event payloads (recursive through dicts, lists, strings).
- [x] `traces_sample_rate=0.0` default + `send_default_pii=False`.

### Scheduler event listeners
- [x] `scheduler.add_listener(_on_scheduler_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)` logs both. Missed jobs hit `WARNING`, errors hit `ERROR`.
- [x] `job_defaults = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 30}` + explicit `timezone=ZoneInfo("UTC")`.
- [x] Scheduler `shutdown(wait=True)` on lifespan exit so in-flight polls finish cleanly.

### Test coverage added
- `tests/test_observability.py` — 24 new tests covering outcome-mapping, metric recorders (service status / poller health / breaker state), Sentry secret scrubbing (webhook URLs, bearer tokens, nested structures), heartbeat fresh/stale detection, heartbeat ping failure swallowing, and HTTP-level `/metrics` + `/healthz` endpoints (both fresh 200 and stale 503).

**Exit criteria met:**
- `/metrics` scrapes cleanly and returns Prometheus text with our metrics (`test_metrics_endpoint_returns_prometheus_text`).
- `/healthz` returns 503 when the scheduler's heartbeat is stale (`test_healthz_stale_returns_503`). A silently-dead scheduler is now visible to launchd, Caddy, and Healthchecks.io.
- Log lines carry `poll_cycle_id` end-to-end (verified via ad-hoc JSON output — a poll starts at the scheduler, and every `logging.getLogger(__name__)` call downstream inherits the cycle ID).
- Sentry init is optional; when configured, a simulated secret leak (Slack webhook URL, bearer token) is redacted before leaving the process.

224 tests passing.

---

## Phase 4 — Data lifecycle (week 4, parallel) — COMPLETE (pool migration deferred)

### Connection pool
- [x] `apply_production_pragmas()` in `app/database.py` is the single source of truth. Applied to the shared connection in `init_db()` and reusable as a factory for future pool connections:
  ```sql
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  PRAGMA busy_timeout = 5000;
  PRAGMA cache_size = -64000;
  PRAGMA mmap_size = 268435456;
  PRAGMA temp_store = MEMORY;
  PRAGMA foreign_keys = ON;
  ```
- [x] `aiosqlitepool` added to requirements as infrastructure for a follow-up reader-pool migration.
- [ ] Migrate call sites from `get_db()` (single shared connection) to `async with pool.connection()` — **deferred**. Current load is far below saturation; the pragmas deliver most of the perf win, and the pool migration unlocks concurrent reads once the dashboard serves enough traffic to care.

### Backup: Litestream
- [x] `deploy/litestream.yml.example` — template supporting local-file, S3, and SFTP replicas (operator picks one).
- [x] `deploy/com.box.it-health-dashboard-litestream.plist.example` — sidecar launchd daemon with `KeepAlive` dict form, `ThrottleInterval`, macOS Keychain-sourced credentials (never hardcoded).
- [x] README "Backup & Disaster Recovery" section documents install → validate → replicate → restore with exact commands.

### Retention
- [x] `app/retention.py::purge_old_rows()` — deletes from `status_events` + `alert_sent_log` with per-table windows (`RETENTION_DAYS_STATUS_EVENTS`, `RETENTION_DAYS_ALERT_SENT_LOG`, default 90 days each; `0` disables).
- [x] `checkpoint_wal()` in `database.py` runs `PRAGMA wal_checkpoint(TRUNCATE)` and logs reclaimed pages — called from retention + the daily checkpoint job.
- [x] Weekly retention + daily WAL-checkpoint jobs scheduled in `scheduler.py` (intervals configurable via `RETENTION_INTERVAL_HOURS`, `WAL_CHECKPOINT_INTERVAL_HOURS`).
- [ ] Daily rollup aggregates for long-term uptime graphs — **deferred**; current SLA queries go back 30 days and fit comfortably in live data.

### Postgres migration path
- Unchanged: current load is ~30 writes/min, three orders of magnitude under SQLite's limit. Not migrating.

### Test coverage added
- `tests/test_retention.py` — 11 tests verifying all 7 production pragmas are applied, `checkpoint_wal()` returns three ints + raises when uninitialized, per-table retention windows delete only the right rows, `0` disables retention, boundary timestamps are preserved, and scheduler entry points swallow setup errors.

**Exit criteria met:**
- All seven production pragmas land on a fresh connection (`test_all_pragmas_applied`).
- Retention deletes only rows past the window; `0` disables it; threshold boundary preserved (`test_boundary_is_inclusive_of_exactly_threshold`).
- `checkpoint_wal()` exits cleanly and returns `(busy, in_wal, checkpointed)`.
- Litestream configs + launchd plist land alongside a clear restore runbook in the README.

235 tests passing.

---

## Phase 5 — UX productionization (week 5) — COMPLETE (TanStack migration + Sheet drawer + Dagre deferred)

### Information architecture
- [x] Grid sorted worst-first: categories ordered by the severity of their worst-ranked service, and within a category tiles sort by `effectiveStatus()` severity rank. Manual-unmonitored services sink to the bottom. Leadership sees the single red tile in the top-left without scanning.
- [x] Stale-data chip in the header ("Last polled Xs ago") colored green/amber/red against `STALE_WARNING_MS` / `STALE_CRITICAL_MS`.
- [x] Active incidents already render in band 2 (existing `IncidentSection`). Dep graph stays behind the `g` shortcut.

### Stale data made visible
- [x] **Never render `operational` when `poller_health != 'healthy'`**. `effectiveStatus()` forces `unknown` for broken pollers so sort, tile, and rollup all agree — the dashboard can't lie by omission.
- [x] Broken-poller tiles render a **dashed border + WifiOff icon** (Lucide) + a tooltip carrying the mechanical `last_failure_reason`. Visually distinct from both operational and legitimately-unknown-manual services.
- [x] Category rollups now report both `N issues` and `M blind` so the difference between "vendor is down" and "poller is dead" stays visible at the rollup level.
- [ ] TanStack Query v5 migration + per-tile "updated Xs ago" + 80% tile fade at 2× poll interval — **deferred**; existing `usePolling` hook + header stale chip cover the critical signal today. TanStack migration requires refactoring all 5 data fetches.

### Status encoding (WCAG 1.4.1)
- [x] Five states, each with **distinct Lucide icon shape AND color**: `CheckCircle2 / AlertTriangle / AlertOctagon / XOctagon / HelpCircle`. Broken-poller state uses `WifiOff`. All icons rendered as proper SVG, not emoji, so scale + stroke are controllable.
- [x] Every status tile + indicator carries `role="img"` + `aria-label` so color is never the sole signal.

### Drill-down
- [ ] **Deferred**: the existing `ServiceDetail` modal works today. Migration to a shadcn `Sheet` would require installing shadcn/ui and reworking the component; not worth it for Phase 5.

### Dep graph
- [ ] **Deferred**: react-force-graph-2d (current) stays. Dagre hierarchical layout + matrix view are follow-up work.

### Keyboard + a11y
- [x] Grid exposes `role="grid"` with a roving tabindex; tiles `role="gridcell"` + rich `aria-label` (including `current_status_detail` and the poller-broken signal).
- [x] Keyboard navigation: **j/k/↓/↑/←/→** move between tiles, **Home/End** jump to worst/last, **Enter** opens the focused tile's detail panel, **Esc** closes overlays, **g** toggles the dependency graph, **?** opens the shortcuts cheatsheet.
- [x] `ShortcutsOverlay` component — `?` anywhere (except inputs) opens a modal listing every binding with `<kbd>` elements.
- [x] `aria-live="polite"` screen-reader region announces high-level summary state changes (`N active incidents` / `All systems operational`) — never per-tile, so readers aren't spammed.
- [x] Global `@media (prefers-reduced-motion: reduce)` CSS block disables animations + transitions for vestibular sensitivity + 24/7 NOC wall displays.
- [x] `:focus-visible` outline on every interactive element (WCAG 2.4.7).

### Loading / error / empty
- [x] Skeletons in `ServiceGrid`, `StatusBanner`, and `Timeline` match actual tile/row shapes.
- [x] Page-level fetch-error banner (`role="alert"`) when any of the polled endpoints fail — tells operators the data may be stale instead of lying with a green dashboard.
- [ ] Widget-level error boundaries + full empty states with icon + title + description + CTA — **deferred** polish.

### Typography
- [x] Inter dropped; **IBM Plex Sans + IBM Plex Mono** via `@fontsource/ibm-plex-*` (self-hosted, no CDN dependency).
- [x] `font-variant-numeric: tabular-nums` globally; `[data-tabular="true"]` opts specific elements (uptime %, `Xs ago`) into mono + tabular for column-stable timestamps.
- [x] Complies with the global frontend-web-baseline rule: "NEVER use Inter, Roboto, Arial, Open Sans, Lato, or system-ui as the primary font".

### Build verification
- [x] `npm run build` succeeds; bundle is 412 KB JS (130 KB gzip) + 33 KB CSS.
- [x] `npx eslint` clean on modified files (pre-existing lint issues in `use-polling.js` left for a separate hooks-refactor pass).
- [x] Backend API (`/api/services`, `/api/services/{id}`) returns `tier`, `poller_health`, `consecutive_failures`, `last_success_at`, `last_failure_reason` so the frontend has everything it needs.

**Exit criteria met:**
- Leadership can eyeball the grid at 3 seconds: the worst service is the top-left tile in the top category, regardless of category name.
- Broken pollers are visually distinct from operational services AND from legitimately-unknown-manual services (dashed border + WifiOff + tooltip).
- Every interactive element is keyboard-navigable; `?` surfaces the full shortcut list.
- `prefers-reduced-motion` honored everywhere; no Inter/system-ui in the font stack.

235 backend tests still passing.

---

## Phase 6 — Platform polish (week 6) — COMPLETE

### CI / quality gates
- [x] `.github/workflows/ci.yml` — `astral-sh/setup-uv@v7` (pinned to `0.11.x`) + ruff + mypy + pytest for the backend; ESLint + `npm run build` for the frontend. Runs on every PR/push, `concurrency.cancel-in-progress` so force-pushes don't pile up.
- [x] `backend/pyproject.toml` expanded with: project metadata, pytest config (asyncio_auto, filterwarnings), `tool.ruff` (target-version py312, sensible rule subset covering E/W/F/I/B/UP/S/SIM/RUF), and `tool.mypy` (`strict=true`, `ignore_missing_imports=true`, per-module overrides for tests + resilience).
- [x] Ran ruff auto-fix across the repo (41 issues auto-resolved); the remaining 7 manual fixes applied: `asyncio` imports on `"asyncio.Lock"` string annotations, `StrEnum` over `(str, Enum)`, `raise ... from e`, unused variable cleanup, dead `instance_keys` line removed, unused `_channel_override` prefix.
- [x] `.pre-commit-config.yaml` — ruff + ruff-format + stdlib hooks (trailing-whitespace, end-of-file-fixer, check-merge-conflict, detect-private-key, check-added-large-files).

### Test coverage
- [x] Poller unit tests with `respx` — already landed in Phase 1 (`tests/test_poller_integration.py`, 12 tests).
- [x] Admin auth tests — already landed in Phase 0 (`tests/test_admin_api.py`, 11 tests covering missing/wrong/unset token + `reason` required).
- [x] Cycle-detection tests — new in `TestCycleHandling` (self-loop, 2-node cycle, 3-node cycle, seed cross-val accepts cycles). Documents that single-hop queries can't infinite-loop even with cycles in the graph.
- [x] Flap suppression — Phase 2 (`tests/test_change_detector.py::TestFlapSuppressionStateMachine` + `TestFlapSuppressionIntegration`, 13 tests).
- [x] Slack rate-limit retry — Phase 0 (`tests/test_slack_alerting.py::TestParseRetryAfter`, 11 tests covering int / HTTP-date / garbage / cap).
- [x] End-to-end integration — new `tests/test_e2e_pipeline.py::test_poll_change_db_alert_pipeline`. Drives three `respx`-mocked polls through `poll_statuspage → detect_changes → process_changes → Slack POST`, asserts flap suppression holds the first major_outage reading, change emits on the second, Slack webhook receives one POST with `<!here>`, and `alerts_sent_total{kind=status_change,severity=critical}` increments exactly once.

### launchd hardening
- [x] `com.box.it-health-dashboard.plist` rewritten with dict-form `KeepAlive` (`SuccessfulExit=false`, `Crashed=true`) so deliberate stops stick.
- [x] `ThrottleInterval=30` prevents crash-loop pegging on bad config.
- [x] `PYTHONUNBUFFERED=1` so stdout reaches the log file in real time.
- [x] `ProcessType=Background`, `SoftResourceLimits.NumberOfFiles=4096`.
- [x] `app/logging_config.py` — new optional `log_file` parameter switches the root handler to `logging.handlers.WatchedFileHandler`, which reopens the file on inode change (newsyslog rotation). Stderr remains the default so launchd's `StandardOutPath` redirection handles rotation via its own plumbing.
- [x] `LOG_FILE` env var added to `Settings`; `main.py` passes it through to `configure_logging`.

### Caddy + secrets
- [x] `deploy/Caddyfile.example` — HTTPS via `tls internal` (or swap for real domain + ACME), security headers (HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, `-Server`), rate-limit zone on `/api/admin/*` (30/min/IP), health check against `/healthz`, JSON access log with size+count rotation.
- [x] `scripts/keychain-secrets.sh` — `provision` / `export` / `get` / `list` commands. System-keychain backed, `-T ""` means no apps are pre-trusted so every retrieval goes through explicit `security(1)`. Known secrets: `SLACK_WEBHOOK_URL`, `POLLER_HEALTH_SLACK_WEBHOOK_URL`, `ADMIN_API_TOKEN`, `SENTRY_DSN`, `HEALTHCHECK_PING_URL`.
- [x] `scripts/run-with-keychain.sh` — launchd wrapper that `eval`s the Keychain exports and `exec`s uvicorn. Point the plist's `ProgramArguments` at this script; the plist itself stays free of secret strings.

**Exit criteria met:**
- CI workflow in place — green locally (`ruff check .` passes, all 240 tests pass).
- launchd plist hardened with dict `KeepAlive` + `ThrottleInterval` + `PYTHONUNBUFFERED` + `ProcessType`.
- Full test coverage for cycle handling + end-to-end pipeline from poll to Slack send.
- Caddy reverse-proxy template + Keychain secret provisioning ready to deploy alongside the main plist.

240 tests passing; `ruff check .` clean on both `app/` and `tests/`.

---

## Phase 7 — Reach (month 2+, optional)

### Webhook receiver — COMPLETE (feature-gated off by default)
- [x] `POST /api/webhooks/statuspage/{service_id}` — HMAC-SHA256 signature verification (`X-Statuspage-Signature`), replay protection via `X-Statuspage-Timestamp` (optional header, 5-min tolerance).
- [x] Handles `component_update` envelope → `normalize_statuspage_component`; `incident` envelope → `normalize_statuspage_indicator` on `impact` field. Unknown shapes 200 without crashing.
- [x] Bypasses flap suppression — webhooks are authoritative. Writes directly to `status_events` + updates `services.current_status`, then calls `process_changes` so Slack + dedup are identical to polled changes.
- [x] `structlog.contextvars` `webhook_id` binding so every downstream log line carries the request ID.
- [x] Unsubscribe confirmation pings ack'd silently (200).
- [x] Feature-gated: `WEBHOOKS_ENABLED=false` (default) → 404; `STATUSPAGE_WEBHOOK_SECRET` unset → 503.
- [x] Requires public reachability — gate on until Cloudflare Tunnel / ingress is in place.

### Deferred Phase 7 items
- **Postmortem automation** — Google-SRE-template Markdown per incident, committed to a repo (Summary → Impact → Root Cause → Timeline → What Went Well/Poorly/Lucky → Action Items categorized Prevent/Mitigate/Detect/Repair).
- **SLO view** — Grafana-style fuel gauge (remaining error budget) + burn-rate line with 1× / 6× / 14.4× thresholds per tier.
- **Multi-burn-rate alerting** — Google SRE canonical pattern: require both long and short window to breach before paging.
- **Slack bot** — `/itstatus okta` slash command, natural-language deferred to post-LLM phase.

---

## Timeline summary

| Phase | Duration | Outcome |
|-------|----------|---------|
| 0 — Stop bleeding | ~1 week | Auth, critical bugs fixed, config validated |
| 1 — Vendor resilience | ~1 week | stamina + purgatory, `unknown` state, per-service health |
| 2 — Alert quality | ~1 week | Dedup, flap suppression, severity routing, dep correlation, ack flow |
| 3 — Observability | ~4 days | structlog, Prometheus, Sentry, dead-man's switch |
| 4 — Data lifecycle | ~3 days | aiosqlitepool, Litestream, retention |
| 5 — UX production | ~1.5 weeks | Stale indicator, Sheet drawer, a11y, keyboard nav |
| 6 — Platform polish | ~4 days | CI, tests, launchd, Caddy, keychain |
| 7 — Reach | ongoing | Webhooks, postmortems, SLOs, multi-burn-rate |

**Total for "mature IT team can rely on it": ~5–6 weeks of focused work.**

---

## Governance

- New work must trace to a phase in this document.
- If a feature doesn't belong in any phase, discuss before starting — don't let the roadmap drift.
- Update phase checkboxes as items land; commit the doc change with the code.
- When Phase N completes, archive its checkbox list under a "Completed" header and move on.
