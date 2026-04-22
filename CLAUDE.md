# IT Service Health Dashboard

## Overview
Internal web dashboard that aggregates real-time health status of ~30 SaaS services IT supports at Box. Polls vendor status pages via Statuspage.io JSON API, Google Workspace JSON feed, Slack's native status API, and RSS/Atom feeds. Enriches with dependency mapping and templated impact statements. Displays a unified status board with timeline view and posts alerts to Slack. Deployed on a Mac Mini behind corporate VPN. Designed for IT engineers (deep triage) and IT leadership / company-wide visibility (situational awareness).

## Roadmap — READ FIRST

- **Active roadmap:** [PRODUCTION-ROADMAP.md](./PRODUCTION-ROADMAP.md) — this is the source of truth for current and upcoming work.
- **Historical v1 spec:** [IMPLEMENTATION-ROADMAP.md](./IMPLEMENTATION-ROADMAP.md) — v1 is **shipped**; this doc is archived for reference only. Do not start new work against it.

All new sessions must read PRODUCTION-ROADMAP.md before proposing work.

## Current Phase
**v2 SHIPPED — Phases 0 through 6 complete.** Auth, vendor resilience, alert quality, observability, data lifecycle, UX productionization, and platform polish all landed. 240 tests passing. The dashboard is production-grade; a mature IT team can rely on it. See PRODUCTION-ROADMAP.md for the exit-criteria detail on each phase.

**Phase 7 is open but optional** — inbound Statuspage webhooks, postmortem automation, SLO views, multi-burn-rate alerting, Slack slash-command bot. Tackle these as demand emerges rather than on a schedule.

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
- **Frontend:** React 18 (Vite 6+) + Tailwind CSS 4+
- **Process manager:** launchd (macOS) for production

## Production-bound additions (planned per PRODUCTION-ROADMAP.md)
- **Resilience:** `stamina` (retries) + `purgatory` (circuit breakers)
- **Observability:** `structlog`, `prometheus-client`, `sentry-sdk[fastapi]`, Healthchecks.io dead-man's switch
- **DB:** `aiosqlitepool` for reader pool, Litestream for backup
- **Frontend:** TanStack Query v5, shadcn/ui `Sheet` + `Command`, Lucide icons, Reagraph/React Flow + Dagre
- **CI:** GitHub Actions with uv; ruff + mypy --strict + pytest

## Development Conventions
- Python: type hints on all functions, async/await for all I/O, no blocking calls
- File naming: snake_case for Python, kebab-case for React files, PascalCase for React components
- Git commits: conventional commits — feat:, fix:, chore:
- Testing: pytest + pytest-asyncio for backend; **`respx`** for httpx mocking in poller tests
- Config: all service definitions and dependency mappings in YAML, never hardcoded
- Logging: structlog JSON (Phase 3); stdlib logging JSON format until then
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
