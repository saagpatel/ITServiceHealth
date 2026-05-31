# IT Service Health Dashboard

Real-time status monitoring dashboard for ~30 SaaS services used by Box IT. Polls vendor status pages every 60 seconds, detects changes, generates impact statements using a service dependency graph, posts Slack alerts, and displays a unified dark-themed operations dashboard.

## Project status

- **v1 (demo-ready) — SHIPPED.** All original spec delivered: polling, normalization, change detection, Slack alerting, React UI, dependency graph, timeline, SLA tracking, incident clustering, auto reports.
- **v2 (production-ready) — SHIPPED.** Phases 0–6 of the production roadmap complete: bearer-token auth, vendor resilience (stamina + purgatory), alert quality (flap suppression, dedup, tier routing, dependency correlation, maintenance windows, flapping-badge UI), observability (structlog, Prometheus `/metrics`, Sentry, Healthchecks.io dead-man's switch), data lifecycle (production pragmas, retention, Litestream streaming + daily `VACUUM INTO` snapshot), UX productionization (severity-sorted grid, distinct poller-broken state, a11y + keyboard nav, Executive/Engineer view toggle, PWA, `recharts` SLA trend), and platform polish (CI, pre-commit, hardened launchd plist, Caddy, Keychain secrets). **356 tests passing.**
- **v2 Phase 2B + Phase 7 — in tree, gated off.** Statuspage inbound webhook receiver (`WEBHOOKS_ENABLED`), Slack ack flow (`SLACK_ACK_ENABLED`), postmortem drafts (`POSTMORTEMS_ENABLED`), SLO fuel-gauge + multi-burn-rate alerting (`SLO_BURN_RATE_ENABLED`), and Slack `/itstatus` slash command (`SLACK_SLASH_ENABLED`) all shipped with tests but default off. Flip each flag once its prerequisites are in place (public endpoint for Slack features; postmortems need only a writable `POSTMORTEMS_DIR`).
- **v2 Phase 7 remainder — optional.** LLM-layer impact statements, Splunk/JSM/ThousandEyes integration. Not on a fixed schedule; add as demand emerges.

**Active roadmap:** [PRODUCTION-ROADMAP.md](./PRODUCTION-ROADMAP.md) — exit-criteria detail for every phase.
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
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated list of allowed CORS origins |
| `SEED_DEMO_DATA` | `false` | Dev-only: auto-populate the DB with synthetic data on boot |
| `POLLER_HEALTH_SLACK_WEBHOOK_URL` | _(none)_ | Separate webhook for poller-health alerts. Falls back to `SLACK_WEBHOOK_URL` when unset. |
| `ALERT_CONFIRM_THRESHOLD_POLLS` | `3` | Consecutive polls required before firing a worsening alert (flap suppression) |
| `ALERT_RECOVERY_THRESHOLD_POLLS` | `2` | Consecutive successes required before firing a recovery alert |
| `ALERT_MIN_STATE_DURATION_SECONDS` | `600` | Minimum dwell time (seconds) for worsening transitions |
| `ALERT_DEDUP_WINDOW_SECONDS` | `86400` | Dedup window for repeat alerts on the same dedup key |
| `DEPENDENCY_CORRELATION_THRESHOLD` | `3` | Min affected dependents before emitting one aggregated upstream alert |
| `BREAKER_THRESHOLD` | `3` | Consecutive failures before the per-host circuit breaker opens |
| `BREAKER_TTL_SECONDS` | `300` | How long an open breaker stays open before half-opening |
| `POLLER_FAILURE_THRESHOLD` | `3` | Consecutive failures before a service's `poller_health` flips to `broken` |
| `LOG_JSON` | `true` | JSON structured logging vs pretty console |
| `LOG_FILE` | _(none)_ | Optional path for Python-side file logging (uses `WatchedFileHandler`). Default: stderr |
| `SENTRY_DSN` | _(none)_ | Enable Sentry error tracking when set |
| `SENTRY_ENVIRONMENT` | `production` | Environment tag reported to Sentry |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.0` | 0.0–1.0 sample rate for Sentry performance traces |
| `HEALTHCHECK_PING_URL` | _(none)_ | Healthchecks.io (or similar) URL pinged by the heartbeat job |
| `HEARTBEAT_INTERVAL_SECONDS` | `30` | How often the heartbeat job marks itself alive |
| `HEARTBEAT_STALE_AFTER_SECONDS` | `120` | `/healthz` returns 503 past this threshold |
| `RETENTION_DAYS_STATUS_EVENTS` | `90` | Auto-purge `status_events` rows older than this (0 = disable) |
| `RETENTION_DAYS_ALERT_SENT_LOG` | `90` | Auto-purge `alert_sent_log` rows older than this (0 = disable) |
| `RETENTION_INTERVAL_HOURS` | `168` | How often the retention job runs |
| `WAL_CHECKPOINT_INTERVAL_HOURS` | `24` | How often the truncating WAL checkpoint runs |
| `BACKUP_DIR` | `backups` | Directory for the daily `VACUUM INTO` snapshot |
| `BACKUP_TIME_HOUR` | `2` | UTC hour for the daily snapshot (independent of Litestream) |
| `BACKUP_RETENTION_DAYS` | `7` | How many daily snapshots to keep |
| `WEBHOOKS_ENABLED` | `false` | Enable inbound Statuspage subscriber webhooks. Requires public reachability and `STATUSPAGE_WEBHOOK_SECRET`. |
| `STATUSPAGE_WEBHOOK_SECRET` | _(none)_ | HMAC-SHA256 shared secret configured in Statuspage → Subscribers → Webhook settings. Required when `WEBHOOKS_ENABLED=true`. |
| `SLACK_ACK_ENABLED` | `false` | Enable the Slack ack-button flow. Requires public reachability and `SLACK_SIGNING_SECRET`. |
| `SLACK_SIGNING_SECRET` | _(none)_ | Signing secret from your Slack app's "Basic Information → App Credentials" page. Required when `SLACK_ACK_ENABLED=true`. |
| `SLACK_SLASH_ENABLED` | `false` | Enable the `/itstatus` slash-command endpoint. Requires public reachability and `SLACK_SIGNING_SECRET`. |
| `POSTMORTEMS_ENABLED` | `false` | Write Google-SRE-style Markdown postmortem drafts on service recovery. |
| `POSTMORTEMS_DIR` | `docs/postmortems` | Directory where postmortem drafts are written (created if absent). |
| `SLO_BURN_RATE_ENABLED` | `false` | Enable the multi-burn-rate SLO alerting scheduler job. |
| `SLO_TARGET_PERCENT` | `99.9` | SLO uptime target used for error-budget calculations (90.0–99.99). |
| `SLO_BURN_RATE_CHECK_INTERVAL_SECONDS` | `300` | How often the burn-rate cycle runs (1–3600). |
| `SLO_BURN_RATE_FAST_THRESHOLD` | `14.4` | Fast-burn multiplier — triggers page-worthy alert (e.g. 14.4× SLO error rate). |
| `SLO_BURN_RATE_SLOW_THRESHOLD` | `6.0` | Slow-burn multiplier — triggers warning-level alert. |
| `SLO_BURN_RATE_TICKET_THRESHOLD` | `1.0` | Ticket-severity burn multiplier — low-urgency notification only. |

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

## Backup & Disaster Recovery (Litestream)

SQLite is the primary store; [Litestream](https://litestream.io) streams WAL frames to an external replica (S3, SFTP, or a second disk) so the dashboard survives a Mac Mini failure.

### Setup

```bash
# 1. Install the binary
brew install benbjohnson/litestream/litestream

# 2. Customize the config template (pick one replica destination)
cp deploy/litestream.yml.example /opt/it-health/deploy/litestream.yml
$EDITOR /opt/it-health/deploy/litestream.yml

# 3. Validate the config before loading it
litestream validate -config /opt/it-health/deploy/litestream.yml

# 4. Install the sidecar launchd daemon
cp deploy/com.box.it-health-dashboard-litestream.plist.example \
   /Library/LaunchDaemons/com.box.it-health-dashboard-litestream.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.box.it-health-dashboard-litestream.plist

# 5. Confirm replication is working
litestream snapshots -config /opt/it-health/deploy/litestream.yml
```

Litestream RPO is ~1 second — after the initial snapshot, every WAL frame ships as it's written.

### Restore

```bash
# 1. Stop the main app so the DB isn't being written to
sudo launchctl bootout system/com.box.it-health-dashboard

# 2. Restore from replica (picks up the latest snapshot + WAL frames)
litestream restore -config /opt/it-health/deploy/litestream.yml \
                   -o /opt/it-health/data.db \
                   /opt/it-health/data.db

# 3. Start the app — it applies pending migrations on boot and resumes polling
sudo launchctl bootstrap system /Library/LaunchDaemons/com.box.it-health-dashboard.plist
```

### Data retention

The dashboard auto-prunes old rows to keep the DB from growing without bound:

| Table | Default retention | Env var |
|-------|------------------|---------|
| `status_events` | 90 days | `RETENTION_DAYS_STATUS_EVENTS` |
| `alert_sent_log` | 90 days | `RETENTION_DAYS_ALERT_SENT_LOG` |

The retention job runs every `RETENTION_INTERVAL_HOURS` (default 168 = weekly) and a truncating WAL checkpoint runs every `WAL_CHECKPOINT_INTERVAL_HOURS` (default 24) so deleted rows actually reclaim disk. Set any retention window to `0` to keep data forever.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Backend health check |
| `/api/services` | GET | All services with status counts |
| `/api/services/{id}` | GET | Service detail with dependencies |
| `/api/timeline` | GET | Recent status change events |
| `/api/summary` | GET | Overall health + active incidents |
| `/api/maintenance` | GET | Upcoming scheduled maintenances |
| `/api/services/uptime` | GET | Per-service per-day worst status over the past 7 days |
| `/api/services/sla` | GET | Per-service uptime % for 24h, 7d, and 30d windows |
| `/api/services/sla/history` | GET | Daily uptime % per service (1–90 days, default 30d) |
| `/api/services/graph` | GET | Service dependency graph (nodes + links) for visualization |
| `/api/services/slo` | GET | Per-service SLO snapshot: error-budget remaining + active burn-rate breaches |
| `/api/admin/status` | POST | Manual status update (requires `Authorization: Bearer $ADMIN_API_TOKEN`) |
| `/healthz` | GET | Dead-man's switch — 200 fresh / 503 stale. Hit by launchd + Healthchecks.io. |
| `/metrics` | GET | Prometheus text exposition. |
| `/api/webhooks/statuspage/{id}` | POST | Inbound Statuspage subscriber webhook, HMAC-verified. 404 unless `WEBHOOKS_ENABLED=true`. |
| `/api/slack/interactivity` | POST | Slack block-actions receiver (ack button). 404 unless `SLACK_ACK_ENABLED=true`. |
| `/api/slack/slash` | POST | Slack `/itstatus` slash-command handler. 503 unless `SLACK_SLASH_ENABLED=true`. |

## What's Next

All production phases (0–6) and the primary Phase 7 reach features are complete. Full exit-criteria history is in [PRODUCTION-ROADMAP.md](./PRODUCTION-ROADMAP.md). Remaining optional work:

- **Phase 7 — LLM layer:** Natural-language impact statements; deferred post-Phase-7.
- **Phase 7 — Integrations:** Splunk, ThousandEyes, Datadog, JSM — deferred to org demand.
