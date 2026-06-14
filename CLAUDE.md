# IT Service Health Dashboard

Private web dashboard aggregating real-time health of ~30 SaaS services in an enterprise IT environment. Polls Statuspage.io JSON API, a cloud productivity suite's JSON feed, a chat vendor's native status API, and RSS/Atom feeds. Enriches with dependency mapping and templated impact statements. Displays a unified status board with timeline view and posts alerts to Slack. Designed for self-hosted, private-network deployment.

## Roadmap

Active source of truth: [PRODUCTION-ROADMAP.md](./PRODUCTION-ROADMAP.md) — read before proposing any work.
Historical v1 spec: [IMPLEMENTATION-ROADMAP.md](./IMPLEMENTATION-ROADMAP.md) — archived, v1 shipped.

## Stack

- **Python** 3.12+ / FastAPI 0.115+ / httpx 0.28+ / aiosqlite 0.21+ / APScheduler 3.10+
- **Config / validation:** PyYAML 6.0+ / Pydantic 2.10+ / feedparser 6.0+
- **Frontend:** React 19 (Vite 8+) + Tailwind CSS 4+; FastAPI serves the built static files
- **Observability:** structlog (JSON), prometheus-client, sentry-sdk[fastapi], Healthchecks.io
- **Resilience:** stamina (retries) + purgatory (per-host circuit breakers)
- **Production process manager:** OS service manager; reverse proxy in front for HTTPS + header auth

## Build / Test / Run

```bash
# Set up backend
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# Build frontend
cd frontend && npm install && npm run build && cd ..

# (Optional) seed demo data
cd backend && python -m scripts.seed_demo_data && cd ..

# Run — serves dashboard + API on port 8000
cd backend && python run.py
```

Open `http://localhost:8000`.

**CI:** GitHub Actions — `uv`, `ruff`, `mypy --strict`, `pytest`; CodeQL analysis. 378 tests passing.

## Conventions

- **I/O:** async/await throughout; no blocking calls in async context.
- **Config:** service definitions and dependency mappings live in `services.yaml`, never hardcoded in Python.
- **HTTP calls:** all wrapped in try/except with timeout, retry (stamina), and graceful degradation; return `unknown` status when a poller fails — not `operational`.
- **Alerting dedup:** use `vendor_incident_id` when available, not message text.
- **Slack integration:** raw httpx POST for webhooks (no slack-sdk); `POST /api/slack/interactivity` for ack flow.
- **Feed priority:** prefer JSON API over RSS when both exist.
- **Poll interval:** minimum 60 seconds (vendor courtesy limit).
- **File naming:** snake_case Python, kebab-case React files, PascalCase React components.
- **Commits:** conventional commits — feat:, fix:, chore:.
- **Testing:** pytest + pytest-asyncio; `respx` for httpx mocking in poller tests.

## Key Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary data source | Statuspage.io `/api/v2/summary.json` | Most vendors use Statuspage.io; JSON, no auth, not rate-limited |
| Cloud productivity suite | Custom JSON feed + RSS | Has its own status dashboard, not Statuspage.io |
| Chat vendor status | Vendor JSON status endpoint | Dedicated JSON status API |
| Database | SQLite + Litestream | Demo-scale + ~1s RPO; Postgres deferred to >100 writes/s |
| Auth | Bearer token on admin endpoints; private access controls for reads | Bearer token required for write endpoints — read-path access controls alone are insufficient |
| Hosting | Self-hosted private deployment | Always-on private access; reverse proxy adds HTTPS + header auth |
| Dep graph layout | Force-directed (react-force-graph-2d) | Dagre hierarchical layout is deferred; force-directed is current default |
| LLM layer | Deferred (post-Phase-7) | Template-based summaries sufficient for v2 |

## Feature Gates (off by default)

Phase 7 code is in-tree but gated. Flip only when a signed callback endpoint is available:

- `WEBHOOKS_ENABLED` — `POST /api/webhooks/statuspage/{service_id}` (HMAC-SHA256; `backend/app/router_webhooks.py`). Bypasses flap suppression; writes directly through the alerting pipeline.
- `SLACK_ACK_ENABLED` — `POST /api/slack/interactivity` (v0 signing-secret; `backend/app/router_slack.py`).
- `POSTMORTEMS_ENABLED` — postmortem automation.
- `SLO_BURN_RATE_ENABLED` — SLO fuel-gauge view + multi-burn-rate alerting.
- `SLACK_SLASH_ENABLED` — Slack `/itstatus` slash command.

**Still open (Phase 7+):** LLM-layer impact statements, Splunk/JSM/ThousandEyes integration.

## Scope Gate

All new work must map to an active phase in PRODUCTION-ROADMAP.md. Splunk, ThousandEyes, Datadog, JSM, and LLM integrations are Phase 7+ — discuss before starting.

<!-- portfolio-context:start -->
# Portfolio Context

## What This Project Is

Private web dashboard that aggregates real-time health status of ~30 SaaS services supported by an enterprise IT team. Polls vendor status pages via Statuspage.io JSON API, a cloud productivity suite's JSON feed, a chat vendor's native status API, and RSS/Atom feeds. Enriches with dependency mapping and templated impact statements. Displays a unified status board with timeline view and posts alerts to Slack. Designed for self-hosted private deployment and for IT engineers (deep triage) plus IT leadership / company-wide visibility (situational awareness).

## Current State

**v2 SHIPPED — Phases 0–6 complete; Phase 2B + Phase 7 (Statuspage inbound webhook + Slack ack) in tree, gated off by default.** Auth, vendor resilience, alert quality, observability, data lifecycle, UX productionization, and platform polish all landed. **378 tests passing.** The dashboard is production-grade; a mature IT team can rely on it. See PRODUCTION-ROADMAP.md for the exit-criteria detail on each phase.

Main also includes a parallel UX sprint that shipped alongside Phase 5:
- **Executive / Engineer view toggle** — `ViewContext` gates the grid vs category summary and engineer-only affordances (graph, timeline, shortcuts).
- **PWA** — `vite-plugin-pwa` registers a service worker with 55-entry precache; `ReloadPrompt` surfaces updates.
- **`recharts` SLA trend** — the service-detail drawer renders 7/30-day uptime history.
- **Daily `VACUUM INTO` backup** — `app/backup.py` writes a snapshot at `settings.backup_time_hour`, independent of Litestream.

**Phase 7 partially landed:**
- **Statuspage inbound webhook** (`POST /api/webhooks/statuspage/{service_id}`, HMAC-SHA256, optional replay protection) — code in `backend/app/router_webhooks.py`, gated by `WEBHOOKS_ENABLED` (default false). Writes directly through the alerting pipeline, bypassing flap suppression.
- **Slack ack flow** (`POST /api/slack/interactivity`, v0 signing-secret) — code in `backend/app/router_slack.py`, gated by `SLACK_ACK_ENABLED` (default false). Block Kit messages only include the Acknowledge button when the flag is true.
- Both features require a signed callback endpoint before flipping the flag. They ship off-by-default so the main app is unaffected.

**Phase 7 further landed** — postmortem automation (`POSTMORTEMS_ENABLED`), SLO fuel-gauge view + multi-burn-rate alerting (`SLO_BURN_RATE_ENABLED`), and Slack `/itstatus` slash command (`SLACK_SLASH_ENABLED`) all shipped, feature-gated off by default. **Still open:** LLM-layer impact statements, Splunk/JSM/ThousandEyes integration.

## Stack

- **Python:** 3.12+
- **Backend framework:** FastAPI 0.115+
- **Async HTTP:** httpx 0.28+
- **Database:** SQLite via aiosqlite 0.21+
- **Task scheduling:** APScheduler 3.10+
- **RSS parsing:** feedparser 6.0+
- **Slack alerting:** httpx (raw webhook POST — no SDK needed)
- **Config:** PyYAML 6.0+
- **Data validation:** Pydantic 2.10+
- **Frontend:** React 19 (Vite 8+) + Tailwind CSS 4+
- **Process manager:** OS service manager for production

## How To Run

```bash
# 1. Clone and enter project
git clone <repo-url> && cd ITServiceHealth

# 2. Set up Python environment
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 3. Build frontend
cd frontend && npm install && npm run build && cd ..

# 4. (Optional) Seed demo data for a populated timeline
cd backend && python -m scripts.seed_demo_data && cd ..

# 5. Run (serves dashboard + API on port 8000)
cd backend && python run.py
```

Open `http://localhost:8000` in your browser.

## Known Risks

- Do not start work that isn't in a PRODUCTION-ROADMAP.md phase. If it doesn't fit, discuss first.
- Do not integrate Splunk, ThousandEyes, Datadog, or JSM — those are Phase 7+.
- Do not build an LLM integration yet — post-Phase-7.
- Do not remove the bearer-token auth on admin endpoints once added. Read-path access controls are not sufficient for write endpoints.
- Do not use synchronous I/O — all network calls must be async.
- Do not hardcode service definitions in Python — they live in services.yaml.
- Do not use slack-sdk — use raw httpx POST for webhook simplicity.
- Do not parse RSS when a JSON API is available — JSON is always preferred.
- Do not poll more frequently than every 60 seconds — courtesy limit with vendor APIs.
- Do not render a service as `operational` when its poller has failed. Use `unknown`.
- Do not dedup alerts on message text. Use `vendor_incident_id` when available.
- Do not use force-directed layout as default for the dependency graph. Use hierarchical (Dagre).

## Next Recommended Move

Use this context plus the README and supporting docs to resume the next active task, then promote the repo beyond minimum-viable by capturing a dedicated handoff, roadmap, or discovery artifact.

<!-- portfolio-context:end -->
