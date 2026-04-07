"""Normalize vendor-specific status strings to our unified 5-state enum."""

from enum import Enum


class ServiceStatus(str, Enum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    PARTIAL_OUTAGE = "partial_outage"
    MAJOR_OUTAGE = "major_outage"
    UNKNOWN = "unknown"


# ── Statuspage.io: Component status → ServiceStatus ────────────────

STATUSPAGE_COMPONENT_MAP: dict[str, ServiceStatus] = {
    "operational": ServiceStatus.OPERATIONAL,
    "degraded_performance": ServiceStatus.DEGRADED,
    "partial_outage": ServiceStatus.PARTIAL_OUTAGE,
    "major_outage": ServiceStatus.MAJOR_OUTAGE,
    "under_maintenance": ServiceStatus.DEGRADED,
}


def normalize_statuspage_component(status: str) -> ServiceStatus:
    """Map a Statuspage.io component status string to ServiceStatus."""
    return STATUSPAGE_COMPONENT_MAP.get(status.lower().strip(), ServiceStatus.UNKNOWN)


# ── Statuspage.io: Page-level indicator → ServiceStatus ────────────

STATUSPAGE_INDICATOR_MAP: dict[str, ServiceStatus] = {
    "none": ServiceStatus.OPERATIONAL,
    "minor": ServiceStatus.DEGRADED,
    "major": ServiceStatus.PARTIAL_OUTAGE,
    "critical": ServiceStatus.MAJOR_OUTAGE,
}


def normalize_statuspage_indicator(indicator: str) -> ServiceStatus:
    """Map a Statuspage.io page-level status indicator to ServiceStatus."""
    return STATUSPAGE_INDICATOR_MAP.get(indicator.lower().strip(), ServiceStatus.UNKNOWN)


# ── Slack Status API ───────────────────────────────────────────────

def normalize_slack_status(response: dict) -> ServiceStatus:
    """Map Slack Status API response to ServiceStatus.

    When status is "ok" and no active incidents → OPERATIONAL.
    Otherwise, map by incident type.
    """
    if not isinstance(response, dict):
        return ServiceStatus.UNKNOWN

    status = response.get("status", "")
    active_incidents = response.get("active_incidents", [])

    if status == "ok" and not active_incidents:
        return ServiceStatus.OPERATIONAL

    if not active_incidents:
        # Non-ok status but no incidents listed — treat as degraded
        return ServiceStatus.DEGRADED

    # Check incident types from most severe to least
    for incident in active_incidents:
        if not isinstance(incident, dict):
            continue
        incident_type = incident.get("type", "")
        if incident_type == "outage":
            return ServiceStatus.MAJOR_OUTAGE

    for incident in active_incidents:
        if not isinstance(incident, dict):
            continue
        incident_type = incident.get("type", "")
        if incident_type == "incident":
            return ServiceStatus.PARTIAL_OUTAGE

    for incident in active_incidents:
        if not isinstance(incident, dict):
            continue
        incident_type = incident.get("type", "")
        if incident_type in ("notice", "maintenance"):
            return ServiceStatus.DEGRADED

    # Active incidents of unknown type
    return ServiceStatus.DEGRADED


# ── Google Workspace ───────────────────────────────────────────────

# Google product name mappings for filtering the incident feed
GOOGLE_PRODUCT_NAMES: dict[str, list[str]] = {
    "google-mail": ["Gmail", "Google Mail"],
    "google-calendar": ["Google Calendar"],
}


def normalize_google_status(incidents: list[dict], service_id: str) -> ServiceStatus:
    """Map Google Workspace incident feed to ServiceStatus for a specific product.

    The incidents.json feed contains incidents for ALL Google Workspace products.
    Filter by matching product names for the given service_id.
    If no active (non-resolved) incidents exist for the product → OPERATIONAL.
    """
    product_names = GOOGLE_PRODUCT_NAMES.get(service_id, [])
    if not product_names:
        return ServiceStatus.UNKNOWN

    for incident in incidents:
        # Check if this incident affects our product
        affected_products = incident.get("affected_products", [])
        product_match = False

        for product in affected_products:
            title = product.get("title", "")
            if title in product_names:
                product_match = True
                break

        if not product_match:
            continue

        # Check if incident is still active (no "end" timestamp means active)
        if incident.get("end"):
            continue

        # Active incident found — check severity from most_recent_update
        most_recent = incident.get("most_recent_update", {})
        status_text = most_recent.get("status", "").lower()

        if "outage" in status_text:
            return ServiceStatus.MAJOR_OUTAGE
        if "disruption" in status_text:
            return ServiceStatus.PARTIAL_OUTAGE

        # Default for any active incident
        return ServiceStatus.DEGRADED

    return ServiceStatus.OPERATIONAL


# ── RSS/Atom Feed (fallback) ──────────────────────────────────────

RSS_SEVERITY_KEYWORDS: dict[ServiceStatus, list[str]] = {
    ServiceStatus.MAJOR_OUTAGE: [
        "major outage", "service outage", "completely unavailable",
    ],
    ServiceStatus.PARTIAL_OUTAGE: [
        "partial outage", "partial disruption", "some users",
    ],
    ServiceStatus.DEGRADED: [
        "degraded", "performance issue", "intermittent", "delays", "investigating",
    ],
    ServiceStatus.OPERATIONAL: [
        "resolved", "operational", "recovered", "fix implemented",
    ],
}


def normalize_rss_title(title: str) -> ServiceStatus:
    """Map an RSS feed item title to ServiceStatus using keyword matching.

    Checks from most severe to least severe, returning on first match.
    """
    lower_title = title.lower().strip()

    # Check from most severe → least severe
    for status in [
        ServiceStatus.MAJOR_OUTAGE,
        ServiceStatus.PARTIAL_OUTAGE,
        ServiceStatus.DEGRADED,
        ServiceStatus.OPERATIONAL,
    ]:
        for keyword in RSS_SEVERITY_KEYWORDS[status]:
            if keyword in lower_title:
                return status

    return ServiceStatus.UNKNOWN
