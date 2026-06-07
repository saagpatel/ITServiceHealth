"""Impact statement template engine.

Generates human-readable impact statements from status changes
and the service dependency graph. Uses simple string templates.
"""

from app.config import settings
from app.poller.change_detector import StatusChange

TEMPLATES = {
    "single_service_degraded": (
        "{service_name} is reporting degraded performance. {vendor_detail}"
    ),
    "single_service_partial": ("{service_name} is experiencing a partial outage. {vendor_detail}"),
    "single_service_major": (
        "\u26a0\ufe0f {service_name} is experiencing a MAJOR OUTAGE. {vendor_detail}"
    ),
    "with_downstream": (" This may impact: {downstream_list}."),
    "sso_degraded": (
        "The identity provider (SSO) is reporting degraded performance. SSO authentication "
        "for all SaaS applications may be affected. Impacted services: {downstream_list}."
    ),
    "sso_outage": (
        "\u26a0\ufe0f The identity provider (SSO) is experiencing an outage. "
        "SSO authentication is unavailable. "
        "Users cannot log into: {downstream_list}. "
        "Advise users with active sessions to avoid logging out."
    ),
    "recovery": ("{service_name} has recovered and is now operational."),
    "overall_healthy": "All {total} monitored services are operational.",
    "overall_incidents": (
        "{incident_count} active incident(s) across {total} monitored services. {incident_summary}"
    ),
}


def generate_impact_statement(
    change: StatusChange,
    downstream: list[dict],
) -> str:
    """Generate an impact statement for a status change.

    Args:
        change: The detected status change.
        downstream: List of downstream services from graph.get_downstream().
    """
    vendor_detail = (change.status_detail or "").strip()
    downstream_names = [d["service_name"] for d in downstream]
    downstream_list = ", ".join(downstream_names) if downstream_names else ""

    # Recovery
    if change.new_status == "operational":
        return TEMPLATES["recovery"].replace("{service_name}", change.service_display_name)

    # Special case: the SSO / identity broker (configurable via
    # SSO_BROKER_SERVICE_ID). An identity-provider outage blocks login to
    # everything downstream, so it gets dedicated impact wording.
    if settings.sso_broker_service_id and change.service_id == settings.sso_broker_service_id:
        if change.new_status in ("major_outage", "partial_outage"):
            return TEMPLATES["sso_outage"].replace("{downstream_list}", downstream_list)
        if change.new_status == "degraded":
            return TEMPLATES["sso_degraded"].replace("{downstream_list}", downstream_list)

    # Generic path: pick template by severity
    template_key = {
        "degraded": "single_service_degraded",
        "partial_outage": "single_service_partial",
        "major_outage": "single_service_major",
    }.get(change.new_status, "single_service_degraded")

    # Use replace instead of .format() to avoid KeyError from vendor details with curly braces
    statement = TEMPLATES[template_key]
    statement = statement.replace("{service_name}", change.service_display_name)
    statement = statement.replace("{vendor_detail}", vendor_detail)
    statement = statement.rstrip()

    # Append downstream impacts if any
    if downstream_names:
        if statement and not statement.endswith((".", "!", "?")):
            statement += "."
        statement += TEMPLATES["with_downstream"].replace(
            "{downstream_list}",
            downstream_list,
        )

    return statement


def generate_summary_text(
    total: int,
    incident_count: int,
    incident_names: list[str],
) -> str:
    """Generate the overall status summary text."""
    if incident_count == 0:
        return TEMPLATES["overall_healthy"].format(total=total)

    incident_summary = ", ".join(incident_names)
    return TEMPLATES["overall_incidents"].format(
        incident_count=incident_count,
        total=total,
        incident_summary=incident_summary,
    )
