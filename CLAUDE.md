# IT Service Health Dashboard

## Overview
Internal web dashboard that aggregates real-time health status of ~30 SaaS services IT supports at Box. Polls vendor status pages via Statuspage.io JSON API, Google Workspace JSON feed, Slack's native status API, and RSS/Atom feeds. Enriches with dependency mapping and templated impact statements. Displays a unified status board with timeline view and posts alerts to Slack. Deployed on a Mac Mini behind corporate VPN. Designed for IT engineers (deep triage) and IT leadership / company-wide visibility (situational awareness).

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

## Development Conventions
- Python: type hints on all functions, async/await for all I/O, no blocking calls
- File naming: snake_case for Python, kebab-case for React files, PascalCase for React components
- Git commits: conventional commits — feat:, fix:, chore:
- Testing: pytest + pytest-asyncio for backend, manual verification for frontend in demo phase
- Config: all service definitions and dependency mappings in YAML, never hardcoded
- Logging: stdlib logging, JSON format, INFO level default
- Error handling: all HTTP calls wrapped in try/except with timeout, retry, graceful degradation

## Current Phase
**Phase 0: Foundation**
See IMPLEMENTATION-ROADMAP.md for full phase details.

## Key Decisions
| Decision | Choice | Why |
|----------|--------|-----|
| Primary data source | Statuspage.io JSON API (`/api/v2/summary.json`) | Most vendors use Statuspage.io; JSON is structured, no auth, not rate-limited |
| Google Workspace | Google's custom JSON feed + RSS | Google uses its own status dashboard, not Statuspage.io |
| Slack status | Slack native Status API (`slack-status.com/api/v2.0.0/current`) | Slack has a dedicated JSON status API |
| Database | SQLite | Demo-scale, zero config, Postgres upgrade path |
| LLM layer | None (v1) | Template-based summaries; LLM deferred to v2 |
| Auth | None — VPN-only | Sufficient for demo |
| Hosting | Mac Mini on corporate network | Always-on, VPN-accessible |
| Slack alerting | Raw httpx POST with Block Kit | No SDK needed for webhooks |
| Frontend serving | FastAPI serves built React static files | Single process, no nginx |
| Scheduled maintenance | Track separately in DB | Surface upcoming maintenance in dashboard |

## Do NOT
- Do not add features not in the current phase of IMPLEMENTATION-ROADMAP.md
- Do not integrate Splunk, ThousandEyes, Datadog, or JSM — those are post-demo (v2+)
- Do not build an LLM integration — v1 uses template-based summaries only
- Do not add user authentication — VPN access is sufficient
- Do not over-engineer the frontend — functional beats flashy for a 2-week demo
- Do not use synchronous I/O — all network calls must be async
- Do not hardcode service definitions in Python — they live in services.yaml
- Do not use slack-sdk — use raw httpx POST for webhook simplicity
- Do not parse RSS when a JSON API is available — JSON is always preferred
- Do not poll more frequently than every 60 seconds
