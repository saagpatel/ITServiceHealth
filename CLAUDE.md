# IT Service Health Dashboard

## Overview
Internal web dashboard that aggregates real-time health status of ~30 SaaS services IT supports at Box. Polls vendor status pages via Statuspage.io JSON API, Google Workspace JSON feed, Slack's native status API, and RSS/Atom feeds. Enriches with dependency mapping and templated impact statements. Displays a unified status board with timeline view and posts alerts to Slack. Deployed on a Mac Mini behind corporate VPN. Designed for IT engineers (deep triage) and IT leadership / company-wide visibility (situational awareness).

## Roadmap — READ FIRST

- **Active roadmap:** [PRODUCTION-ROADMAP.md](./PRODUCTION-ROADMAP.md) — this is the source of truth for current and upcoming work.
- **Historical v1 spec:** [IMPLEMENTATION-ROADMAP.md](./IMPLEMENTATION-ROADMAP.md) — v1 is **shipped**; this doc is archived for reference only. Do not start new work against it.

All new sessions must read PRODUCTION-ROADMAP.md before proposing work.

## Current Phase
**v2 SHIPPED — Phases 0–6 complete; Phase 2B + Phase 7 (Statuspage inbound webhook + Slack ack) in tree, gated off by default.** Auth, vendor resilience, alert quality, observability, data lifecycle, UX productionization, and platform polish all landed. **356 tests passing.** The dashboard is production-grade; a mature IT team can rely on it. See PRODUCTION-ROADMAP.md for the exit-criteria detail on each phase.

Main also includes a parallel UX sprint that shipped alongside Phase 5:
- **Executive / Engineer view toggle** — `ViewContext` gates the grid vs category summary and engineer-only affordances (graph, timeline, shortcuts).
- **PWA** — `vite-plugin-pwa` registers a service worker with 55-entry precache; `ReloadPrompt` surfaces updates.
- **`recharts` SLA trend** — the service-detail drawer renders 7/30-day uptime history.
- **Daily `VACUUM INTO` backup** — `app/backup.py` writes a snapshot at `settings.backup_time_hour`, independent of Litestream.

**Phase 7 partially landed:**
- **Statuspage inbound webhook** (`POST /api/webhooks/statuspage/{service_id}`, HMAC-SHA256, optional replay protection) — code in `backend/app/router_webhooks.py`, gated by `WEBHOOKS_ENABLED` (default false). Writes directly through the alerting pipeline, bypassing flap suppression.
- **Slack ack flow** (`POST /api/slack/interactivity`, v0 signing-secret) — code in `backend/app/router_slack.py`, gated by `SLACK_ACK_ENABLED` (default false). Block Kit messages only include the Acknowledge button when the flag is true.
- Both features require a public endpoint (Cloudflare Tunnel / Caddy allowlist / ngrok) before flipping the flag. They ship off-by-default so the main app is unaffected.

**Phase 7 further landed** — postmortem automation (`POSTMORTEMS_ENABLED`), SLO fuel-gauge view + multi-burn-rate alerting (`SLO_BURN_RATE_ENABLED`), and Slack `/itstatus` slash command (`SLACK_SLASH_ENABLED`) all shipped, feature-gated off by default. **Still open:** LLM-layer impact statements, Splunk/JSM/ThousandEyes integration.

## Tech Stack
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
- **Process manager:** launchd (macOS) for production

## Shipped production additions (Phases 0–6)

All of these are in `requirements.txt` and active:
- **Resilience:** `stamina` (retries) + `purgatory` (per-host circuit breakers)
- **Observability:** `structlog`, `prometheus-client`, `sentry-sdk[fastapi]`, Healthchecks.io dead-man's switch, `QueueListener` offloads file I/O
- **DB:** `aiosqlitepool` in requirements (pool migration deferred); Litestream config template in `deploy/`
- **Frontend:** Lucide icons, `recharts` SLA trend, IBM Plex fonts
- **CI:** GitHub Actions — `uv`, `ruff`, `mypy --strict`, `pytest`; CodeQL analysis

## Deferred UX additions (optional)
- TanStack Query v5, shadcn/ui `Sheet` + `Command`, Dagre hierarchical dep graph

## Development Conventions
- Python: type hints on all functions, async/await for all I/O, no blocking calls
- File naming: snake_case for Python, kebab-case for React files, PascalCase for React components
- Git commits: conventional commits — feat:, fix:, chore:
- Testing: pytest + pytest-asyncio for backend; **`respx`** for httpx mocking in poller tests
- Config: all service definitions and dependency mappings in YAML, never hardcoded
- Logging: structlog JSON (Phase 3 complete — structlog is active)
- Error handling: all HTTP calls wrapped in try/except with timeout, retry, graceful degradation

## Key Decisions
| Decision | Choice | Why |
|----------|--------|-----|
| Primary data source | Statuspage.io JSON API (`/api/v2/summary.json`) | Most vendors use Statuspage.io; JSON is structured, no auth, not rate-limited |
| Google Workspace | Google's custom JSON feed + RSS | Google uses its own status dashboard, not Statuspage.io |
| Slack status | Slack native Status API (`slack-status.com/api/v2.0.0/current`) | Slack has a dedicated JSON status API |
| Database | SQLite + Litestream (Phase 4) | Demo-scale + ~1s RPO backup; Postgres deferred to >100 writes/s |
| LLM layer | None (v1) | Template-based summaries; LLM deferred to post-Phase-7 |
| Auth | Bearer token on admin endpoints (Phase 0); VPN-only for reads | Demo had no auth; production requires it for writes |
| Hosting | Mac Mini on corporate network, Caddy in front (Phase 6) | Always-on, VPN-accessible; Caddy adds HTTPS + header auth |
| Slack alerting | Raw httpx POST with Block Kit; ack buttons (Phase 2) | No SDK needed for webhooks; ack flow requires interactivity endpoint |
| Frontend serving | FastAPI serves built React static files | Single process, no nginx |
| Scheduled maintenance | First-class DB table (Phase 2) | Vendor windows auto-populated; suppresses alerts |

## Do NOT
- Do not start work that isn't in a PRODUCTION-ROADMAP.md phase. If it doesn't fit, discuss first.
- Do not integrate Splunk, ThousandEyes, Datadog, or JSM — those are Phase 7+.
- Do not build an LLM integration yet — post-Phase-7.
- Do not remove the bearer-token auth on admin endpoints once added. VPN is not sufficient for write endpoints.
- Do not use synchronous I/O — all network calls must be async.
- Do not hardcode service definitions in Python — they live in services.yaml.
- Do not use slack-sdk — use raw httpx POST for webhook simplicity.
- Do not parse RSS when a JSON API is available — JSON is always preferred.
- Do not poll more frequently than every 60 seconds — courtesy limit with vendor APIs.
- Do not render a service as `operational` when its poller has failed. Use `unknown`.
- Do not dedup alerts on message text. Use `vendor_incident_id` when available.
- Do not use force-directed layout as default for the dependency graph. Use hierarchical (Dagre).

<!-- portfolio-context:start -->
# Portfolio Context

## What This Project Is

Internal web dashboard that aggregates real-time health status of ~30 SaaS services IT supports at Box. Polls vendor status pages via Statuspage.io JSON API, Google Workspace JSON feed, Slack's native status API, and RSS/Atom feeds. Enriches with dependency mapping and templated impact statements. Displays a unified status board with timeline view and posts alerts to Slack. Deployed on a Mac Mini behind corporate VPN. Designed for IT engineers (deep triage) and IT leadership / company-wide visibility (situational awareness).

## Current State

**v2 SHIPPED — Phases 0–6 complete; Phase 2B + Phase 7 (Statuspage inbound webhook + Slack ack) in tree, gated off by default.** Auth, vendor resilience, alert quality, observability, data lifecycle, UX productionization, and platform polish all landed. **356 tests passing.** The dashboard is production-grade; a mature IT team can rely on it. See PRODUCTION-ROADMAP.md for the exit-criteria detail on each phase.

Main also includes a parallel UX sprint that shipped alongside Phase 5:
- **Executive / Engineer view toggle** — `ViewContext` gates the grid vs category summary and engineer-only affordances (graph, timeline, shortcuts).
- **PWA** — `vite-plugin-pwa` registers a service worker with 55-entry precache; `ReloadPrompt` surfaces updates.
- **`recharts` SLA trend** — the service-detail drawer renders 7/30-day uptime history.
- **Daily `VACUUM INTO` backup** — `app/backup.py` writes a snapshot at `settings.backup_time_hour`, independent of Litestream.

**Phase 7 partially landed:**
- **Statuspage inbound webhook** (`POST /api/webhooks/statuspage/{service_id}`, HMAC-SHA256, optional replay protection) — code in `backend/app/router_webhooks.py`, gated by `WEBHOOKS_ENABLED` (default false). Writes directly through the alerting pipeline, bypassing flap suppression.
- **Slack ack flow** (`POST /api/slack/interactivity`, v0 signing-secret) — code in `backend/app/router_slack.py`, gated by `SLACK_ACK_ENABLED` (default false). Block Kit messages only include the Acknowledge button when the flag is true.
- Both features require a public endpoint (Cloudflare Tunnel / Caddy allowlist / ngrok) before flipping the flag. They ship off-by-default so the main app is unaffected.

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
- **Process manager:** launchd (macOS) for production

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
- Do not remove the bearer-token auth on admin endpoints once added. VPN is not sufficient for write endpoints.
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
