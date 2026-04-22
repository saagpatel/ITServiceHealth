# IT Service Health Dashboard

Real-time status monitoring dashboard for ~30 SaaS services used by Box IT. Polls vendor status pages every 60 seconds, detects changes, generates impact statements using a service dependency graph, posts Slack alerts, and displays a unified dark-themed operations dashboard.

## Project status

- **v1 (demo-ready) — SHIPPED.** All original spec delivered: polling, normalization, change detection, Slack alerting, React UI, dependency graph, timeline, SLA tracking, incident clustering, auto reports.
- **v2 (production-ready) — IN PROGRESS.** Hardening the tool so a mature IT team can rely on it: auth, resilience, alert hygiene, observability, accessibility.

**Active roadmap:** [PRODUCTION-ROADMAP.md](./PRODUCTION-ROADMAP.md) — source of truth for current work.
**Historical spec:** [IMPLEMENTATION-ROADMAP.md](./IMPLEMENTATION-ROADMAP.md) — archived; v1 is complete.

## Architecture

```
[Vendor Status Pages]
    |-- Statuspage.io JSON API (15 services)
    |-- Slack Status API (1 service)
    |-- Google Workspace JSON feed (2 services)
    |-- Manual updates via POST /api/admin/status (11 services)
              | (async poll every 60s)
       [Poll Orchestrator]
              |
       [Status Normalizer] --> 5-state enum: operational|degraded|partial|major|unknown
              |
       [Change Detector] --> diff against DB, write status_events
              |
       [Impact Statement Engine] --> dependency graph + templates
       [Slack Alerter] --> Block Kit message to #service-validation
       [SQLite Writer] --> update services, insert events
              |
       [FastAPI REST API] --> /api/services, /api/timeline, /api/summary
              |
       [React Dashboard] <-- auto-refresh 30s
```

## Quick Start

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

## Accessing the Dashboard

The dashboard runs on a Mac Mini on the corporate network. Access via VPN at:

```
http://<mac-mini-ip>:8000
```

No authentication required — VPN access is the security boundary.

## Service Categories

| Category | Services |
|----------|----------|
| Identity & Access | Okta, Duo |
| Productivity | Box, DocuSign, Google Mail, Google Calendar, Conga, Eptura |
| Collaboration | Slack, Zoom, RingCentral |
| Engineering | Confluence, Jira, Jira Service Management, SnapLogic |
| HR & People | Greenhouse, Workday, Cornerstone |
| Finance | SAP Concur, Coupa, NetSuite, Zuora |
| Sales & CRM | Salesforce, Partner Portal |
| Marketing | Iterable, Marketo |
| Network & VPN | Juniper VPN |
| Support | Zendesk, Lithium |

## Manual Status Updates

For services without automated polling (Okta, Workday, Concur, etc.), update status via curl. **Admin endpoints require a bearer token** (set `ADMIN_API_TOKEN` in your env).

```bash
export TOKEN="your-admin-token"

# Set a service to degraded
curl -X POST http://localhost:8000/api/admin/status \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"service_id": "workday", "new_status": "degraded", "detail": "Slow login page", "reason": "Reported by user in #it-help"}'

# Set to major outage
curl -X POST http://localhost:8000/api/admin/status \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"service_id": "okta", "new_status": "major_outage", "detail": "SSO completely unavailable", "reason": "Confirmed with vendor"}'

# Resolve (set back to operational)
curl -X POST http://localhost:8000/api/admin/status \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"service_id": "okta", "new_status": "operational", "reason": "Vendor posted recovery"}'
```

Valid statuses: `operational`, `degraded`, `partial_outage`, `major_outage`, `unknown`. The `reason` field is required for audit trail.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_WEBHOOK_URL` | _(none)_ | Slack incoming webhook URL for #service-validation alerts |
| `DATABASE_PATH` | `data.db` | SQLite database file path |
| `POLL_INTERVAL_SECONDS` | `60` | How often to poll vendor status pages (1–3600) |
| `HOST` | `127.0.0.1` | Server bind address (`0.0.0.0` for network access) |
| `PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `ADMIN_API_TOKEN` | _(none)_ | Bearer token required for `/api/admin/*` endpoints. If unset, admin endpoints refuse all requests. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated list of allowed CORS origins |

Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
# Edit .env with your values
```

## Development Mode

Run frontend and backend separately with hot reload:

```bash
# Terminal 1: Backend (auto-reload on Python changes)
cd backend && python run.py --dev

# Terminal 2: Frontend (Vite dev server with HMR)
cd frontend && npm run dev
```

Frontend dev server at `localhost:5173` proxies `/api/*` to `localhost:8000`.

## Production Deployment (Mac Mini)

```bash
# 1. Clone and set up (same as Quick Start steps 1-4)

# 2. Configure environment
cp .env.example backend/.env
# Edit backend/.env: set HOST=0.0.0.0, SLACK_WEBHOOK_URL=<your-url>

# 3. Update plist paths
# Edit com.box.it-health-dashboard.plist:
#   - Replace /path/to/ with actual project path
#   - Add SLACK_WEBHOOK_URL

# 4. Install launchd service
sudo cp com.box.it-health-dashboard.plist /Library/LaunchDaemons/
sudo launchctl bootstrap system /Library/LaunchDaemons/com.box.it-health-dashboard.plist

# 5. Verify
curl http://localhost:8000/api/health

# 6. Open firewall (if needed)
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add $(which python3)
```

Manage the service:
```bash
# Stop
sudo launchctl bootout system/com.box.it-health-dashboard

# Start
sudo launchctl bootstrap system /Library/LaunchDaemons/com.box.it-health-dashboard.plist

# View logs
tail -f /var/log/it-health-dashboard.log
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Backend health check |
| `/api/services` | GET | All services with status counts |
| `/api/services/{id}` | GET | Service detail with dependencies |
| `/api/timeline` | GET | Recent status change events |
| `/api/summary` | GET | Overall health + active incidents |
| `/api/maintenance` | GET | Upcoming scheduled maintenances |
| `/api/admin/status` | POST | Manual status update |

## What's Next

Current production-hardening work is tracked in [PRODUCTION-ROADMAP.md](./PRODUCTION-ROADMAP.md). Highlights:

- **Phase 0 — Critical fixes:** admin auth, config validation, correctness bugs
- **Phase 1 — Vendor resilience:** stamina retries + purgatory circuit breakers, per-service health tracking, `unknown` state
- **Phase 2 — Alert hygiene:** flap suppression, dedup, severity routing, dependency correlation, ack flow
- **Phase 3 — Observability:** structlog, Prometheus metrics, Sentry, Healthchecks.io dead-man's switch
- **Phase 4 — Data lifecycle:** connection pool, Litestream backup, retention
- **Phase 5 — UX production:** TanStack Query, stale-data chip, right-side drawer, a11y + keyboard nav
- **Phase 6 — Platform polish:** CI, Caddy, keychain secrets, launchd hardening
- **Phase 7 — Reach (post-v2):** inbound Statuspage webhooks, postmortem automation, SLO views, LLM layer, Splunk/JSM/ThousandEyes integration
