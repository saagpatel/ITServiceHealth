# IT Service Health Dashboard — Implementation Roadmap

> **ARCHIVED — v1 SHIPPED.**
>
> This document describes the original v1 build and is preserved for historical reference. All v1 phases (foundation, polling, normalization, change detection, Slack alerting, React UI, dependency graph, timeline, SLA tracking, incident clustering, auto reports) are **complete and running**.
>
> **The active roadmap is [PRODUCTION-ROADMAP.md](./PRODUCTION-ROADMAP.md).** All new work — resilience, alert hygiene, observability, UX hardening — tracks there. Do not start new work against this document.

## Architecture

### System Overview
```
[Vendor Status Pages]
    ├── Statuspage.io JSON API (/api/v2/summary.json) — ~20 services
    ├── A cloud productivity suite JSON feed + RSS — 2 services (Mail, Calendar)
    ├── the chat-platform status API (chat-status.example.com/api/v2.0.0/current) — 1 service
    └── Manual updates via POST /api/admin/status — ~10 services
              ↓ (async poll every 60s via APScheduler)
       [Polling Workers]
              ↓
       [Status Normalizer] — vendor-specific → 5-state enum
              ↓
       [Change Detector] — diff against last known state
              ↓ (on change)
       ┌──────────────────────┐
       │  [Template Engine]   │ — generate impact statements from dependency graph
       │  [Slack Alerter]     │ — POST Block Kit message to the ops-alert channel webhook
       │  [SQLite Writer]     │ — insert status_events row, update services row
       └──────────────────────┘
              ↓
       [FastAPI REST API] — serves JSON to frontend
              ↓
       [React Dashboard] ← (auto-refresh 30s via polling)
```

### File Structure
```
it-service-health/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI app, lifespan (scheduler start/stop), static file mount
│   │   ├── config.py              # Settings via pydantic-settings: env vars, paths, poll interval
│   │   ├── database.py            # SQLite init, migrations, connection pool (aiosqlite)
│   │   ├── models.py              # Pydantic response models (API output shapes)
│   │   ├── schemas.py             # Internal DB row dataclasses
│   │   ├── router_services.py     # GET /api/services, GET /api/services/{id}
│   │   ├── router_timeline.py     # GET /api/timeline
│   │   ├── router_summary.py      # GET /api/summary
│   │   ├── router_admin.py        # POST /api/admin/status (manual updates)
│   │   ├── router_health.py       # GET /api/health
│   │   ├── poller/
│   │   │   ├── __init__.py
│   │   │   ├── scheduler.py       # APScheduler async setup, 60s interval, error handling
│   │   │   ├── statuspage_poller.py  # Statuspage.io JSON API poller (handles ~20 services)
│   │   │   ├── product_feed_poller.py   # Cloud productivity suite status poller (JSON feed + RSS)
│   │   │   ├── current_status_poller.py    # Chat-platform status API poller
│   │   │   ├── rss_poller.py      # Fallback RSS/Atom poller for services without JSON API
│   │   │   ├── normalizer.py      # Vendor status string → ServiceStatus enum mapping
│   │   │   └── change_detector.py # Diff current vs stored state, emit change events
│   │   ├── alerting/
│   │   │   ├── __init__.py
│   │   │   ├── slack.py           # Slack incoming webhook POST with Block Kit formatting
│   │   │   └── templates.py       # Impact statement template engine using dependency graph
│   │   └── dependencies/
│   │       ├── __init__.py
│   │       └── graph.py           # Load dependencies.yaml, query upstream/downstream impacts
│   ├── config/
│   │   ├── services.yaml          # All 30+ services with API URLs, types, categories
│   │   └── dependencies.yaml      # Service dependency graph
│   ├── tests/
│   │   ├── conftest.py            # Shared fixtures: test DB, mock httpx client
│   │   ├── test_normalizer.py     # Status string normalization
│   │   ├── test_templates.py      # Impact statement generation
│   │   ├── test_dependencies.py   # Dependency graph queries
│   │   ├── test_statuspage_poller.py  # Mock Statuspage.io responses
│   │   ├── test_change_detector.py    # State diff logic
│   │   └── test_api.py            # FastAPI endpoint tests
│   ├── requirements.txt
│   └── run.py                     # Entry point: uvicorn with reload flag
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── components/
│   │   │   ├── StatusBoard.jsx        # Grid of all services grouped by category
│   │   │   ├── ServiceCard.jsx        # Individual service tile with status indicator
│   │   │   ├── SituationBanner.jsx    # Top banner: overall health + active incidents
│   │   │   ├── Timeline.jsx           # Chronological status change feed
│   │   │   ├── ServiceDetail.jsx      # Expanded view: deps, history, vendor link
│   │   │   ├── StatusBadge.jsx        # Colored pill/dot for status states
│   │   │   ├── MaintenanceBanner.jsx  # Upcoming scheduled maintenance notices
│   │   │   └── LastUpdated.jsx        # "Last polled X seconds ago" indicator
│   │   ├── hooks/
│   │   │   └── usePolling.js          # Auto-refresh hook with stale detection
│   │   ├── lib/
│   │   │   ├── api.js                 # Fetch wrapper pointing to /api/*
│   │   │   └── constants.js           # Status colors, category labels, refresh interval
│   │   └── styles/
│   │       └── index.css              # Tailwind imports + custom status colors
│   ├── index.html
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── package.json
├── scripts/
│   ├── seed_demo_data.py          # Backfill realistic historical incidents for demo
│   └── test_webhooks.py           # Manual Slack webhook tester
├── CLAUDE.md
├── IMPLEMENTATION-ROADMAP.md
├── README.md
├── .env.example                   # Template for environment variables
└── .gitignore
```

### Data Model

```sql
-- Service registry: static + current state for each monitored service
CREATE TABLE services (
    id TEXT PRIMARY KEY,                            -- slug: "identity-provider", "cloud-mail", "chat-platform"
    display_name TEXT NOT NULL,                     -- "Identity Provider", "Cloud Mail", "Chat Platform"
    category TEXT NOT NULL,                         -- see categories below
    poll_type TEXT NOT NULL DEFAULT 'manual',       -- "statuspage_json", "product_feed_json", "current_status_api", "rss", "manual"
    poll_url TEXT,                                  -- API/feed URL to poll (NULL if manual)
    statuspage_component_name TEXT,                 -- for statuspage_json: match this component name in API response
    status_page_url TEXT,                           -- vendor public status page URL for linking
    current_status TEXT NOT NULL DEFAULT 'unknown', -- "operational", "degraded", "partial_outage", "major_outage", "unknown"
    current_status_detail TEXT,                     -- vendor's description of current issue
    last_polled_at DATETIME,
    last_status_change_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Status events: every status change creates a row
CREATE TABLE status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL REFERENCES services(id),
    previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    vendor_title TEXT,                              -- incident title from vendor
    vendor_detail TEXT,                             -- incident description/body from vendor
    impact_statement TEXT,                          -- generated template-based impact text
    source TEXT NOT NULL DEFAULT 'statuspage_json', -- "statuspage_json", "product_feed_json", "current_status_api", "rss", "manual"
    vendor_incident_id TEXT,                        -- vendor's incident ID for deduplication
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_events_service_id ON status_events(service_id);
CREATE INDEX idx_events_created_at ON status_events(created_at);
CREATE INDEX idx_events_service_created ON status_events(service_id, created_at);
CREATE INDEX idx_events_vendor_incident ON status_events(vendor_incident_id);

-- Service dependencies: directed graph
CREATE TABLE service_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upstream_service_id TEXT NOT NULL REFERENCES services(id),
    downstream_service_id TEXT NOT NULL REFERENCES services(id),
    impact_description TEXT NOT NULL,               -- "SSO authentication unavailable"
    severity TEXT NOT NULL DEFAULT 'high',           -- "critical", "high", "medium", "low"
    UNIQUE(upstream_service_id, downstream_service_id)
);
CREATE INDEX idx_deps_upstream ON service_dependencies(upstream_service_id);
CREATE INDEX idx_deps_downstream ON service_dependencies(downstream_service_id);

-- Scheduled maintenance: track vendor-announced maintenance windows
CREATE TABLE scheduled_maintenances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL REFERENCES services(id),
    vendor_maintenance_id TEXT,                     -- vendor's ID for deduplication
    title TEXT NOT NULL,
    description TEXT,
    scheduled_for DATETIME NOT NULL,
    scheduled_until DATETIME,
    status TEXT NOT NULL DEFAULT 'scheduled',       -- "scheduled", "in_progress", "verifying", "completed"
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_maint_service ON scheduled_maintenances(service_id);
CREATE INDEX idx_maint_scheduled ON scheduled_maintenances(scheduled_for);
```

---

## Complete Service Catalog (services.yaml)

This is the full service registry. Claude Code should generate the actual `services.yaml` from this specification.

### Poll Type: `statuspage_json`
These vendors use Atlassian Statuspage. Poll their `/api/v2/summary.json` endpoint which returns component statuses + unresolved incidents + scheduled maintenances in a single call. No authentication required. Not rate-limited (it's the public status API).

**Statuspage.io JSON API response shape:**
```json
{
  "page": { "id": "...", "name": "...", "url": "..." },
  "status": { "indicator": "none|minor|major|critical", "description": "All Systems Operational" },
  "components": [
    { "id": "...", "name": "Component Name", "status": "operational|degraded_performance|partial_outage|major_outage|under_maintenance", "description": "..." }
  ],
  "incidents": [ { "id": "...", "name": "...", "status": "investigating|identified|monitoring|resolved", "impact": "none|minor|major|critical", "incident_updates": [...] } ],
  "scheduled_maintenances": [ { "id": "...", "name": "...", "status": "scheduled|in_progress|verifying|completed", "scheduled_for": "...", "scheduled_until": "..." } ]
}
```

| Service | Status Page Base URL | summary.json URL | Component to Match | Category |
|---------|---------------------|-------------------|--------------------|----------|
| Content platform | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | Match overall page status or relevant component | productivity |
| Identity provider (SSO) | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | Use page-level status (vendor has cell-specific pages; use main) | identity |
| MFA | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | "MFA Security" or page-level | identity |
| E-signature tool | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | Page-level or "eSignature" component | productivity |
| Video conferencing | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | "Meetings", "Phone", or page-level | collaboration |
| Finance tools (expense) | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | Page-level | finance |
| Document automation | (verify Statuspage URL) | Verify at runtime — may use custom domain | Page-level | productivity |
| Integration platform | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | Page-level | engineering |
| Finance tools (billing) | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | Page-level | finance |
| HR tools (LMS) | (vendor status domain — verify at runtime) | Verify at runtime | Page-level | hr |
| Marketing tools (email) | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | Page-level | marketing |
| Marketing tools (automation) | (vendor status domain — verify at runtime) | Verify — may be under a parent vendor's status page | "Marketing Automation" component | marketing |
| HR tools (ATS) | (vendor status domain — verify at runtime) | Verify at runtime | Page-level | hr |
| Space management | (verify) | Verify — may have been acquired | Page-level | productivity |
| CRM | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | Page-level or instance-specific | sales |
| Support platform | (vendor status domain — verify at runtime) | `https://<vendor-status-domain>/api/v2/summary.json` | Page-level | support |

**IMPORTANT: Claude Code must verify every URL during Phase 0 by running `curl <url>` and confirming valid JSON is returned. Some URLs may have changed or use custom Statuspage domains. If a URL fails, search for the vendor's status page and find the correct Statuspage.io URL, then check if `/api/v2/summary.json` is accessible.**

### Poll Type: `current_status_api`
Some collaboration vendors expose a dedicated current-status API, not Statuspage.

| Service | API URL | Category |
|---------|---------|----------|
| Chat platform | `https://chat-status.example.com/api/v2.0.0/current` | collaboration |

**Current-status API response shape:**
```json
{
  "status": "ok|active",
  "date_created": "2018-09-07T18:34:15-07:00",
  "date_updated": "2018-09-07T18:34:15-07:00",
  "active_incidents": [
    {
      "id": 1234,
      "date_created": "...",
      "date_updated": "...",
      "title": "Some customers may experience...",
      "type": "incident|notice|maintenance",
      "status": "active|resolved",
      "url": "https://status.example.com/2024-01/...",
      "services": ["Login/SSO", "Messaging", "Connections", ...],
      "notes": [{ "date_created": "...", "body": "..." }]
    }
  ]
}
```
When `status` is `"ok"` and `active_incidents` is empty → operational. Otherwise map by incident type/impact.

### Poll Type: `product_feed_json`
A cloud productivity suite uses its own status dashboard with a JSON feed and RSS.

| Service | JSON URL | RSS URL | Category |
|---------|----------|---------|----------|
| Cloud Mail | `https://feed.example.com/incidents.json` | `https://feed.example.com/rss` | productivity |
| Cloud Calendar | (same JSON feed — filter by product) | (same RSS feed) | productivity |

**Cloud productivity suite JSON feed:** Contains incidents for ALL products in the suite. Filter by `service_name` field matching the relevant products. The feed provides `most_recent_update.status` which maps to severity. RSS feed at `https://feed.example.com/rss` is a fallback.

**Note:** The cloud productivity suite's JSON feed returns incident *history*, not a real-time component status like Statuspage. For current status: if no active (non-resolved) incidents exist for the product → operational. If active incidents exist → map severity.

### Poll Type: `rss`
Fallback for any service that has an RSS/Atom feed but not a known JSON API.

| Service | Feed URL | Category |
|---------|----------|----------|
| Telephony | (find RSS URL from status page) | collaboration |

### Poll Type: `manual`
These services have no automated monitoring feeds. IT engineers update status via `curl POST`.

| Service | Status Page URL (for linking) | Category |
|---------|-------------------------------|----------|
| Team wiki | status.atlassian.com (has JSON API — consider upgrading to statuspage_json) | engineering |
| Ticketing / ITSM system | status.atlassian.com (same — consider statuspage_json with component filter) | engineering |
| ServiceDesk | status.atlassian.com (same) | engineering |
| Finance tools (procurement) | (no known status page) | finance |
| VPN | (no public status page) | networking |
| Community platform | (no known status page) | other |
| Finance tools (ERP) | (verify — vendor may have a status page) | finance |
| HR system | (verify — vendor has a trust site) | hr |
| Partner portal | (CRM instance — use CRM status) | sales |

**NOTE: The team wiki, ticketing / ITSM system, and ServiceDesk are all products from the same vendor (Atlassian). Atlassian has a Statuspage.io-based status page at `https://status.atlassian.com/api/v2/summary.json`. Claude Code should verify this API and if accessible, upgrade these from `manual` to `statuspage_json` with appropriate component name filters. This would reduce manual services from ~10 to ~7.**

### Service Categories
```yaml
categories:
  identity: "Identity & Access"        # identity provider (SSO), MFA
  productivity: "Productivity"          # content platform, e-signature, cloud mail, cloud calendar, space management, document automation
  collaboration: "Collaboration"        # chat platform, video conferencing, telephony
  engineering: "Engineering"            # ticketing / ITSM system, team wiki, ServiceDesk, integration platform
  hr: "HR & People"                     # HR tools (ATS), HR system, HR tools (LMS)
  finance: "Finance"                    # finance tools (expense), finance tools (procurement), finance tools (ERP), finance tools (billing)
  sales: "Sales & CRM"                 # CRM, partner portal
  marketing: "Marketing"               # marketing tools (email), marketing tools (automation)
  networking: "Network & VPN"           # VPN
  support: "Support"                    # support platform
```

---

## Status Normalization Rules

The normalizer must handle status strings from multiple vendors and map them to our 5-state enum.

### Our Status Enum
```python
class ServiceStatus(str, Enum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    PARTIAL_OUTAGE = "partial_outage"
    MAJOR_OUTAGE = "major_outage"
    UNKNOWN = "unknown"
```

### Statuspage.io Component Status Mapping
```python
STATUSPAGE_MAP = {
    "operational": ServiceStatus.OPERATIONAL,
    "degraded_performance": ServiceStatus.DEGRADED,
    "partial_outage": ServiceStatus.PARTIAL_OUTAGE,
    "major_outage": ServiceStatus.MAJOR_OUTAGE,
    "under_maintenance": ServiceStatus.DEGRADED,  # treat maintenance as degraded
}
```

### Statuspage.io Page-Level Indicator Mapping
```python
STATUSPAGE_INDICATOR_MAP = {
    "none": ServiceStatus.OPERATIONAL,
    "minor": ServiceStatus.DEGRADED,
    "major": ServiceStatus.PARTIAL_OUTAGE,
    "critical": ServiceStatus.MAJOR_OUTAGE,
}
```

### Current-status API mapping
```python
def normalize_current_status(response: dict) -> ServiceStatus:
    if response["status"] == "ok" and not response.get("active_incidents"):
        return ServiceStatus.OPERATIONAL
    incidents = response.get("active_incidents", [])
    if any(i["type"] == "outage" for i in incidents):
        return ServiceStatus.MAJOR_OUTAGE
    if any(i["type"] == "incident" for i in incidents):
        return ServiceStatus.PARTIAL_OUTAGE
    if any(i["type"] in ("notice", "maintenance") for i in incidents):
        return ServiceStatus.DEGRADED
    return ServiceStatus.DEGRADED  # default if active but unknown type
```

### Product-feed mapping
```python
# Cloud productivity suite incidents have severity levels in updates
# If no active incident for the product → OPERATIONAL
# If active incident exists → DEGRADED (default), escalate based on description keywords
```

### RSS Feed Mapping (fallback)
```python
RSS_TITLE_KEYWORDS = {
    ServiceStatus.MAJOR_OUTAGE: ["major outage", "service outage", "completely unavailable"],
    ServiceStatus.PARTIAL_OUTAGE: ["partial outage", "partial disruption", "some users"],
    ServiceStatus.DEGRADED: ["degraded", "performance issue", "intermittent", "delays", "investigating"],
    ServiceStatus.OPERATIONAL: ["resolved", "operational", "recovered", "fix implemented"],
}
```

---

## Dependency Graph (dependencies.yaml)

```yaml
# Format: upstream → downstream (when upstream breaks, downstream is impacted)
dependencies:
  # Identity & Access — highest blast radius
  identity-provider:
    - service: content-platform
      impact: "Content platform SSO login unavailable"
      severity: critical
    - service: chat-platform
      impact: "Chat platform SSO login may fail for new sessions"
      severity: critical
    - service: video-conferencing
      impact: "Video conferencing SSO login unavailable"
      severity: critical
    - service: crm
      impact: "CRM SSO login unavailable"
      severity: critical
    - service: itsm
      impact: "Ticketing / ITSM system SSO login unavailable"
      severity: high
    - service: team-wiki
      impact: "Team wiki SSO login unavailable"
      severity: high
    - service: finance-expense
      impact: "Finance tools (expense) SSO login unavailable"
      severity: high
    - service: hr-system
      impact: "HR system SSO login unavailable"
      severity: high
    - service: hr-ats
      impact: "HR tools (ATS) SSO login unavailable"
      severity: medium
    - service: esignature
      impact: "E-signature tool SSO login unavailable"
      severity: medium
    - service: support-platform
      impact: "Support platform SSO login unavailable"
      severity: medium
    - service: finance-erp
      impact: "Finance tools (ERP) SSO login unavailable"
      severity: medium

  mfa:
    - service: identity-provider
      impact: "MFA push notifications unavailable; identity provider login may require fallback methods"
      severity: critical

  # Collaboration dependencies
  chat-platform:
    - service: servicedesk
      impact: "Chat-based IT support channel and bot unavailable"
      severity: high

  # Cloud productivity suite
  cloud-mail:
    - service: cloud-calendar
      impact: "Calendar notifications and email invites may be delayed"
      severity: medium

  # Sales & CRM
  crm:
    - service: partner-portal
      impact: "Partner Portal is hosted on the CRM — full outage expected"
      severity: critical

  # Network
  vpn:
    - service: all_internal
      impact: "VPN outage affects remote access to all internal services"
      severity: critical
```

---

## Impact Statement Templates

```python
TEMPLATES = {
    "single_service_degraded": (
        "{service_name} is reporting degraded performance. "
        "{vendor_detail}"
    ),
    "single_service_partial": (
        "{service_name} is experiencing a partial outage. "
        "{vendor_detail}"
    ),
    "single_service_major": (
        "⚠️ {service_name} is experiencing a MAJOR OUTAGE. "
        "{vendor_detail}"
    ),
    "with_downstream": (
        " This may impact: {downstream_list}."
    ),
    "sso_degraded": (
        "The identity provider (SSO) is reporting degraded performance. SSO authentication "
        "for all SaaS applications may be affected. Impacted services: {downstream_list}."
    ),
    "sso_outage": (
        "⚠️ The identity provider (SSO) is experiencing an outage. SSO authentication is unavailable. "
        "Users cannot log into: {downstream_list}. "
        "Advise users with active sessions to avoid logging out."
    ),
    "vpn_outage": (
        "⚠️ VPN is experiencing an outage. "
        "Remote users cannot access internal services. "
        "On-site users are not affected."
    ),
    "overall_healthy": "All {total} monitored services are operational.",
    "overall_incidents": (
        "{incident_count} active incident(s) across {total} monitored services. "
        "{incident_summary}"
    ),
}
```

---

## Slack Alert Format (Block Kit)

Alerts posted to the ops-alert channel use Slack Block Kit for rich formatting:

```python
def build_slack_alert(service_name: str, old_status: str, new_status: str,
                      impact_statement: str, status_page_url: str | None) -> dict:
    """Build a Slack Block Kit payload for a status change alert."""
    emoji_map = {
        "operational": "✅",
        "degraded": "🟡",
        "partial_outage": "🟠",
        "major_outage": "🔴",
        "unknown": "⚫",
    }
    emoji = emoji_map.get(new_status, "⚫")
    
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {service_name} Status Change",
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Previous:*\n{old_status.replace('_', ' ').title()}"},
                {"type": "mrkdwn", "text": f"*Current:*\n{new_status.replace('_', ' ').title()}"},
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Impact:*\n{impact_statement}"}
        },
    ]
    
    if status_page_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View Status Page"},
                "url": status_page_url,
                "action_id": "view_status_page"
            }]
        })
    
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"IT Service Health Dashboard • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"}]
    })
    
    return {
        "text": f"{emoji} {service_name}: {old_status} → {new_status}",  # fallback for notifications
        "blocks": blocks
    }
```

**Slack Webhook POST:**
```python
async def send_slack_alert(webhook_url: str, payload: dict) -> bool:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        return response.status_code == 200
```

**Rate limit:** Slack incoming webhooks allow 1 message per second. If multiple services change simultaneously, batch them into a single message or add a small delay between sends.

---

## API Contracts

### Internal REST API

| Endpoint | Method | Description | Query Params |
|----------|--------|-------------|--------------|
| `/api/services` | GET | All services with current status | `category` (optional filter) |
| `/api/services/{service_id}` | GET | Single service + deps + recent events | — |
| `/api/timeline` | GET | Recent status events, newest first | `limit` (default 50), `service_id` (optional) |
| `/api/summary` | GET | Overall health + active incidents | — |
| `/api/maintenance` | GET | Upcoming/active scheduled maintenances | — |
| `/api/admin/status` | POST | Manually update service status | — |
| `/api/health` | GET | Backend health check | — |

### Response Types

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum

class ServiceStatus(str, Enum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    PARTIAL_OUTAGE = "partial_outage"
    MAJOR_OUTAGE = "major_outage"
    UNKNOWN = "unknown"

class ServiceResponse(BaseModel):
    id: str
    display_name: str
    category: str
    current_status: ServiceStatus
    current_status_detail: Optional[str] = None
    poll_type: str
    status_page_url: Optional[str] = None
    last_polled_at: Optional[datetime] = None
    last_status_change_at: Optional[datetime] = None

class DependencyResponse(BaseModel):
    service_id: str
    service_name: str
    impact_description: str
    severity: str
    current_status: ServiceStatus  # include current status of the related service

class StatusEventResponse(BaseModel):
    id: int
    service_id: str
    service_name: str
    previous_status: ServiceStatus
    new_status: ServiceStatus
    vendor_title: Optional[str] = None
    vendor_detail: Optional[str] = None
    impact_statement: Optional[str] = None
    source: str
    created_at: datetime

class ServiceDetailResponse(BaseModel):
    service: ServiceResponse
    downstream_impacts: list[DependencyResponse]
    upstream_dependencies: list[DependencyResponse]
    recent_events: list[StatusEventResponse]  # last 10

class ServiceListResponse(BaseModel):
    services: list[ServiceResponse]
    total: int
    healthy_count: int
    degraded_count: int
    outage_count: int
    unknown_count: int

class TimelineResponse(BaseModel):
    events: list[StatusEventResponse]
    total: int

class ActiveIncident(BaseModel):
    service: ServiceResponse
    impact_statement: str
    affected_services: list[str]
    started_at: datetime

class MaintenanceResponse(BaseModel):
    id: int
    service_id: str
    service_name: str
    title: str
    description: Optional[str] = None
    scheduled_for: datetime
    scheduled_until: Optional[datetime] = None
    status: str

class SummaryResponse(BaseModel):
    overall_status: ServiceStatus
    status_text: str
    active_incidents: list[ActiveIncident]
    upcoming_maintenances: list[MaintenanceResponse]
    total_services: int
    healthy_count: int
    degraded_count: int
    outage_count: int
    unknown_count: int
    last_poll_at: Optional[datetime] = None

class StatusUpdateRequest(BaseModel):
    service_id: str
    new_status: ServiceStatus
    detail: Optional[str] = None
```

### Dependencies

```bash
# Backend
pip install fastapi==0.115.* uvicorn[standard]==0.34.* aiosqlite==0.21.* \
    feedparser==6.0.* httpx==0.28.* apscheduler==3.10.* pyyaml==6.0.* \
    pydantic==2.10.* pytest==8.* pytest-asyncio==0.24.*

# Frontend
npm create vite@latest frontend -- --template react
cd frontend
npm install
npm install -D tailwindcss @tailwindcss/vite
```

---

## Scope Boundaries

**In scope (v1 demo):**
- Unified status board for all ~30 services
- Statuspage.io JSON API polling for ~20 services
- Chat-platform status API polling
- Cloud productivity suite JSON/RSS polling
- Manual status update API for remaining services
- Service dependency graph with impact statement templates
- Timeline view of recent status changes
- Situation banner with template-generated summary
- Scheduled maintenance tracking and display
- Slack Block Kit alerts to the ops-alert channel on status changes
- Auto-refresh dashboard (30s polling)
- Service categorization and grouped display
- "Last updated" indicator showing poll freshness

**Out of scope (v1):**
- LLM-generated summaries (v2)
- Splunk log correlation
- ThousandEyes / Datadog integration
- JSM ticket correlation
- GitHub change tracking
- Slack bot interface
- User authentication
- Historical analytics / SLA reporting
- Email notifications
- Incident acknowledgment / ownership tracking

**Deferred:**
- LLM summary layer → v2 (post-demo, once API key secured)
- Splunk + JSM correlation → Phase 2
- Slack bot → Phase 3
- ThousandEyes + Datadog → Phase 3

---

## Security & Credentials

- **Slack webhook URL:** env var `SLACK_WEBHOOK_URL` — never in git
- **All vendor status APIs:** public, no auth
- **No user data collected:** dashboard is read-only, no PII
- **Network boundary:** Mac Mini on the internal network, internal-network-only access
- **SQLite:** local file on Mac Mini, not exposed
- `.env` file in `.gitignore`, `.env.example` committed as template

---

## Phase 0: Foundation (Days 1–2)

**Objective:** Scaffolded project with working database, service registry populated from YAML, and one Statuspage.io JSON API poll succeeding.

**Tasks:**

1. Initialize project directory structure matching the file structure above — **Acceptance:** All directories and `__init__.py` files exist; `python -c "from app.main import app; print('OK')"` prints OK
2. Create `requirements.txt` and install dependencies — **Acceptance:** `pip install -r requirements.txt` succeeds with no errors
3. Implement `config.py` with pydantic-settings — **Acceptance:** Reads `SLACK_WEBHOOK_URL`, `DATABASE_PATH`, `POLL_INTERVAL_SECONDS` from env vars with sensible defaults
4. Implement `database.py` with async SQLite setup — **Acceptance:** Running init function creates `data.db` with all 4 tables and all indexes; verify with `sqlite3 data.db ".tables"` showing `services status_events service_dependencies scheduled_maintenances`
5. Create `config/services.yaml` with all ~30 services — **Acceptance:** File contains every service from the catalog above. For each statuspage_json service, the `poll_url` has been verified by running `curl <url>` and confirming valid JSON response. Services with unverified URLs are noted with comments.
6. Create `config/dependencies.yaml` — **Acceptance:** Contains the full dependency graph from this roadmap
7. Implement YAML loader + DB seeder — **Acceptance:** Run seeder → `SELECT count(*) FROM services` returns correct count (≥28)
8. Implement `statuspage_poller.py` — poll ONE service (identity provider) via its Statuspage.io summary URL — **Acceptance:** Returns parsed status, prints component statuses to console
9. Implement `normalizer.py` with all mapping tables — **Acceptance:** `pytest tests/test_normalizer.py` passes with tests for every vendor mapping

**Verification checklist:**
- [ ] `cd backend && python run.py` → server starts on port 8000
- [ ] `curl localhost:8000/api/health` → `{"status": "ok"}`
- [ ] `sqlite3 data.db "SELECT count(*) FROM services"` → ≥28
- [ ] `sqlite3 data.db "SELECT id, poll_type FROM services WHERE poll_type='statuspage_json'"` → ~16-20 rows
- [ ] `pytest tests/test_normalizer.py` → all pass
- [ ] Manual test: `python -c "import asyncio; from app.poller.statuspage_poller import poll_service; asyncio.run(poll_service('identity-provider'))"` → prints identity provider status

**Risks:**
- Some Statuspage.io URLs may have changed or use custom domains → **Mitigation:** Phase 0 Task 5 explicitly requires verifying each URL. Document any failures and fall back to RSS or manual.
- The cloud productivity suite JSON feed URL may not be publicly documented and could change → **Mitigation:** Fall back to RSS at `https://feed.example.com/rss`

---

## Phase 1: Data Pipeline (Days 3–4)

**Objective:** All automated pollers running on schedule, status changes detected and stored, Slack alerts firing, manual status API working. All API endpoints returning real data.

**Tasks:**

1. Extend `statuspage_poller.py` to handle ALL statuspage_json services in a single poll cycle — **Acceptance:** One async function iterates `services.yaml`, polls each statuspage_json service, handles errors per-service (one failure doesn't stop others)
2. Implement `current_status_poller.py` for the chat-platform status API — **Acceptance:** Polls `https://chat-status.example.com/api/v2.0.0/current`, normalizes response to ServiceStatus
3. Implement `product_feed_poller.py` for the cloud productivity suite — **Acceptance:** Fetches JSON/RSS feed, filters for Cloud Mail and Cloud Calendar, returns per-product status
4. Implement `change_detector.py` — **Acceptance:** Compares poll result against `services.current_status` in DB; on change: inserts `status_events` row, updates `services` row, returns list of changes
5. Implement `dependencies/graph.py` — **Acceptance:** `test_dependencies.py` passes; `get_downstream("identity-provider")` returns all SSO-dependent services with impact descriptions
6. Implement `alerting/templates.py` — **Acceptance:** `test_templates.py` passes; generates correct impact statements for identity provider outage, VPN outage, generic service degradation
7. Implement `alerting/slack.py` with Block Kit formatting — **Acceptance:** Trigger a test change → message appears in the ops-alert channel with header, status fields, impact text, and button linking to vendor status page
8. Implement `scheduler.py` tying it all together — **Acceptance:** On app startup, scheduler begins 60s poll cycle. Logs show all services polled. No unhandled exceptions.
9. Implement `router_admin.py` POST `/api/admin/status` — **Acceptance:** `curl -X POST localhost:8000/api/admin/status -H 'Content-Type: application/json' -d '{"service_id":"hr-system","new_status":"degraded","detail":"Slow response times"}'` → returns updated service, creates status_event, triggers Slack alert
10. Implement all GET API endpoints (services, timeline, summary, maintenance) — **Acceptance:** Each returns correct JSON matching the Pydantic response models

**Verification checklist:**
- [ ] `curl localhost:8000/api/services | python -m json.tool` → all services with real statuses
- [ ] `curl localhost:8000/api/timeline` → events (test with manual status change if no real incidents)
- [ ] `curl localhost:8000/api/summary` → correct counts, active incidents list, maintenance list
- [ ] `curl localhost:8000/api/maintenance` → upcoming maintenances from Statuspage.io
- [ ] POST a degraded status manually → Slack Block Kit message appears in the ops-alert channel within 5 seconds
- [ ] Wait 2 minutes → see at least 2 poll cycles in logs, no errors
- [ ] `pytest tests/` → all tests pass

**Risks:**
- Slack webhook rate limit (1 msg/sec) during mass status changes → **Mitigation:** If >3 services change in one cycle, batch into single message
- Some Statuspage.io pages may not have meaningful component names (just "API", "Web") → **Mitigation:** Use page-level `status.indicator` as primary, component status as detail only
- Google JSON feed may be rate-limited or return stale data → **Mitigation:** 60s poll interval is conservative; fall back to RSS if JSON fails

---

## Phase 2: Frontend Dashboard (Days 6–8)

**Objective:** Fully functional React dashboard with status board, situation banner, timeline, service detail, and maintenance notices.

**Tasks:**

1. Scaffold React + Vite + Tailwind project — **Acceptance:** `npm run dev` → page loads at localhost:5173
2. Define constants: status colors, category labels, API base URL — **Acceptance:** `constants.js` exports color map (green/yellow/orange/red/gray), category display names, 30s refresh interval
3. Build `usePolling` hook — **Acceptance:** Generic hook that fetches a URL every N seconds, returns `{ data, loading, error, lastUpdated }`, only re-renders when data changes (deep compare or hash)
4. Build `StatusBoard` component — **Acceptance:** Grid of service cards grouped by category with section headers. Categories sorted: Identity, Productivity, Collaboration, Engineering, HR, Finance, Sales, Marketing, Network, Support
5. Build `ServiceCard` component — **Acceptance:** Shows service name + colored status dot/pill. Hover shows status detail. Click opens ServiceDetail.
6. Build `SituationBanner` component — **Acceptance:** Green banner "All Systems Operational" when healthy. Yellow/orange/red when incidents active, showing count + service names + impact text
7. Build `MaintenanceBanner` component — **Acceptance:** If upcoming maintenances exist, show amber notice below situation banner with service name, time, and description
8. Build `Timeline` component — **Acceptance:** Chronological feed of status events with timestamps, service names, old→new status with colored indicators, and impact text. Most recent first. Auto-updates via polling.
9. Build `ServiceDetail` panel — **Acceptance:** Click a service → slide-in panel showing: current status, vendor status page link (opens in new tab), dependency lists (upstream + downstream with their current statuses), last 10 status events
10. Build `LastUpdated` component — **Acceptance:** Shows "Last updated X seconds ago" in footer, turns yellow if >90 seconds stale, red if >180 seconds
11. Configure Vite proxy for development — **Acceptance:** `vite.config.js` proxies `/api/*` to `localhost:8000` for dev mode

**Verification checklist:**
- [ ] `cd frontend && npm run dev` → dashboard loads at localhost:5173 showing all ~30 services
- [ ] Status colors accurately reflect backend data (compare with `curl /api/services`)
- [ ] Banner shows correct state (verify against `curl /api/summary`)
- [ ] Clicking a service shows detail panel with dependencies
- [ ] Timeline updates within 30 seconds of POSTing a manual status change
- [ ] Maintenance banner appears if any scheduled maintenances exist
- [ ] Works in Chrome and Safari
- [ ] No CORS errors in console

**Risks:**
- CORS between Vite (5173) and FastAPI (8000) in dev → **Mitigation:** Add CORSMiddleware to FastAPI allowing `localhost:5173`. In production, serve from FastAPI static mount (no CORS needed).
- Auto-refresh causing flicker → **Mitigation:** Only update React state when data has actually changed (compare JSON hash or use `useMemo`)

---

## Phase 3: Integration + Deploy + Demo Prep (Days 9–10)

**Objective:** Production build deployed on Mac Mini, accessible via VPN, Slack alerting live, seeded with demo data, README written.

**Tasks:**

1. Build frontend for production — **Acceptance:** `npm run build` → `dist/` directory; files are <2MB total
2. Configure FastAPI to serve static frontend — **Acceptance:** Mount `dist/` as static files at `/`; `curl localhost:8000/` returns `index.html`
3. Create `scripts/seed_demo_data.py` — **Acceptance:** Seeds 5-7 historical incidents over the past 7 days across different services with realistic timestamps, status progressions (investigating → identified → monitoring → resolved), and impact statements. Timeline view looks populated, not empty.
4. Create `.env.example` — **Acceptance:** Contains `SLACK_WEBHOOK_URL=`, `DATABASE_PATH=./data.db`, `POLL_INTERVAL_SECONDS=60`, `HOST=0.0.0.0`, `PORT=8000`
5. Create `com.company.it-health-dashboard.plist` launchd service file — **Acceptance:** Starts on boot, restarts on crash, logs to `/var/log/it-health-dashboard.log`
6. Deploy to Mac Mini — **Acceptance:** Clone repo, install deps, configure `.env`, load launchd plist, verify `curl <host>:8000/api/health` from another machine on the internal network
7. Open macOS firewall for port 8000 — **Acceptance:** Dashboard accessible from another laptop on the internal network
8. End-to-end smoke test — **Acceptance:** From a different machine on the internal network: load dashboard, see live statuses, verify at least 16+ services show non-"unknown" statuses, trigger manual status change, see Slack alert + dashboard update within 60s
9. Write `README.md` — **Acceptance:** Contains: project overview, architecture diagram (text), how to access (URL), what it shows, how to manually update services (curl examples), environment setup instructions, what's planned next (v2 features)
10. Prepare demo script — **Acceptance:** 2-3 talking points: (a) show live dashboard with real statuses, (b) trigger a simulated incident and show Slack alert + dashboard update, (c) click a service to show dependency mapping

**Verification checklist:**
- [ ] From another laptop on the internal network: `http://<host>:8000` → dashboard loads
- [ ] ≥16 services show live statuses (not all "unknown")
- [ ] Manual-only services show "unknown" or manually-set statuses
- [ ] Timeline shows seeded + any real events
- [ ] POST manual outage → Slack Block Kit alert fires within 5s, dashboard updates within 30s
- [ ] launchd service survives `kill` (restarts automatically)
- [ ] README is clear enough that a teammate could set up a second instance

**Risks:**
- Mac Mini firewall blocking inbound → **Mitigation:** Run `sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/python3` or disable firewall for port 8000 specifically. Test from another machine early in Phase 3.
- DNS/hostname on the internal network → **Mitigation:** Use raw IP for demo; request DNS alias from network team if project continues
- stale data after Mac Mini sleep → **Mitigation:** Disable sleep in System Preferences → Energy Saver. Verify poll cycle resumes after network reconnect.

---

## Post-Demo Roadmap (v2+)

**v2 — LLM Intelligence Layer (Weeks 3-4):**
- Secure enterprise LLM API key (Claude API or OpenAI)
- Replace template engine with LLM-generated situation summaries
- Add "Ask about this incident" natural language query on service detail panel

**v3 — Internal Signal Correlation (Weeks 5-8):**
- Splunk integration: pull auth failure logs, network errors, app-specific events
- ITSM ticket correlation: count open tickets mentioning affected service names
- Dashboard enrichment: "Identity provider (SSO) degraded + 47 SSO tickets in last 30min + Splunk showing auth failures"

**v4 — Proactive Detection + Slack Bot (Weeks 9-12):**
- ThousandEyes + Datadog integration for network and APM signals
- Anomaly detection: alert when ticket volume spikes before vendor status page updates
- Slack bot: `@it-agent what's going on with the identity provider?` → returns correlated intelligence
- GitHub change correlation: "These 3 config changes were deployed in the last hour"
