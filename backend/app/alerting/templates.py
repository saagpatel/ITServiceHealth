"""Impact statement template engine.

Generates human-readable impact statements from status changes
and the service dependency graph. Uses simple string templates.
"""

from app.poller.change_detector import StatusChange

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
        "\u26a0\ufe0f {service_name} is experiencing a MAJOR OUTAGE. "
        "{vendor_detail}"
    ),
    "with_downstream": (
        " This may impact: {downstream_list}."
    ),
    "okta_degraded": (
        "Okta is reporting degraded performance. SSO authentication "
        "for all SaaS applications may be affected. Impacted services: {downstream_list}."
    ),
    "okta_outage": (
        "\u26a0\ufe0f Okta is experiencing an outage. SSO authentication is unavailable. "
        "Users cannot log into: {downstream_list}. "
        "Advise users with active sessions to avoid logging out."
    ),
    "vpn_outage": (
        "\u26a0\ufe0f VPN (Juniper) is experiencing an outage. "
        "Remote users cannot access internal services. "
        "On-site users are not affected."
    ),
    "recovery": (
        "{service_name} has recovered and is now operational."
    ),
    "overall_healthy": "All {total} monitored services are operational.",
    "overall_incidents": (
        "{incident_count} active incident(s) across {total} monitored services. "
        "{incident_summary}"
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
        return TEMPLATES["recovery"].format(service_name=change.service_display_name)

    # Special case: Okta
    if change.service_id == "okta":
        if change.new_status in ("major_outage", "partial_outage"):
            return TEMPLATES["okta_outage"].format(downstream_list=downstream_list)
        if change.new_status == "degraded":
            return TEMPLATES["okta_degraded"].format(downstream_list=downstream_list)

    # Special case: VPN
    if change.service_id == "juniper-vpn":
        return TEMPLATES["vpn_outage"]

    # Generic path: pick template by severity
    template_key = {
        "degraded": "single_service_degraded",
        "partial_outage": "single_service_partial",
        "major_outage": "single_service_major",
    }.get(change.new_status, "single_service_degraded")

    statement = TEMPLATES[template_key].format(
        service_name=change.service_display_name,
        vendor_detail=vendor_detail,
    ).rstrip()

    # Append downstream impacts if any
    if downstream_names:
        statement += TEMPLATES["with_downstream"].format(
            downstream_list=downstream_list,
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
