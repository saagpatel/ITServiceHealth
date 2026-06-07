"""Tests for impact statement templates."""

from app.alerting.templates import generate_impact_statement, generate_summary_text
from app.config import settings
from app.poller.change_detector import StatusChange


def _make_change(
    service_id="test-svc",
    display_name="Test Service",
    previous="operational",
    new="degraded",
    detail=None,
    poll_type="statuspage_json",
    url=None,
):
    return StatusChange(
        service_id=service_id,
        service_display_name=display_name,
        previous_status=previous,
        new_status=new,
        status_detail=detail,
        poll_type=poll_type,
        status_page_url=url,
    )


def _make_downstream(names):
    return [
        {
            "service_name": n,
            "service_id": n.lower(),
            "severity": "high",
            "impact_description": f"{n} impacted",
            "current_status": "operational",
        }
        for n in names
    ]


class TestGenerateImpactStatement:
    def test_generic_degraded(self):
        change = _make_change(new="degraded", detail="Slow responses")
        result = generate_impact_statement(change, [])
        assert "degraded performance" in result
        assert "Slow responses" in result

    def test_generic_partial_outage(self):
        change = _make_change(new="partial_outage", detail="Some users affected")
        result = generate_impact_statement(change, [])
        assert "partial outage" in result

    def test_generic_major_outage(self):
        change = _make_change(new="major_outage", detail="Fully down")
        result = generate_impact_statement(change, [])
        assert "MAJOR OUTAGE" in result

    def test_with_downstream(self):
        change = _make_change(new="degraded", detail="Slow")
        downstream = _make_downstream(["Ticketing", "Team Wiki"])
        result = generate_impact_statement(change, downstream)
        assert "may impact" in result
        assert "Ticketing" in result
        assert "Team Wiki" in result

    def test_recovery(self):
        change = _make_change(new="operational", previous="degraded")
        result = generate_impact_statement(change, [])
        assert "recovered" in result
        assert "operational" in result

    def test_sso_broker_outage(self, monkeypatch):
        monkeypatch.setattr(settings, "sso_broker_service_id", "identity-provider")
        change = _make_change(
            service_id="identity-provider", display_name="Identity Provider", new="major_outage"
        )
        downstream = _make_downstream(["Service A", "Service B", "Service C"])
        result = generate_impact_statement(change, downstream)
        assert "SSO authentication is unavailable" in result
        assert "Service A" in result
        assert "avoid logging out" in result

    def test_sso_broker_degraded(self, monkeypatch):
        monkeypatch.setattr(settings, "sso_broker_service_id", "identity-provider")
        change = _make_change(
            service_id="identity-provider", display_name="Identity Provider", new="degraded"
        )
        downstream = _make_downstream(["Service A", "Service B"])
        result = generate_impact_statement(change, downstream)
        assert "SSO authentication" in result
        assert "may be affected" in result

    def test_sso_broker_partial_uses_outage_template(self, monkeypatch):
        monkeypatch.setattr(settings, "sso_broker_service_id", "identity-provider")
        change = _make_change(
            service_id="identity-provider", display_name="Identity Provider", new="partial_outage"
        )
        downstream = _make_downstream(["Service A"])
        result = generate_impact_statement(change, downstream)
        assert "SSO authentication is unavailable" in result

    def test_sso_broker_unset_uses_generic_template(self, monkeypatch):
        # With no broker configured, even the identity service gets the
        # generic severity template — no hardcoded vendor special-casing.
        monkeypatch.setattr(settings, "sso_broker_service_id", None)
        change = _make_change(
            service_id="identity-provider", display_name="Identity Provider", new="major_outage"
        )
        result = generate_impact_statement(change, [])
        assert "MAJOR OUTAGE" in result
        assert "SSO authentication" not in result

    def test_generic_major_outage_service(self):
        change = _make_change(
            service_id="some-service", display_name="Some Service", new="major_outage"
        )
        result = generate_impact_statement(change, [])
        assert "Some Service" in result
        assert "MAJOR OUTAGE" in result

    def test_empty_vendor_detail(self):
        change = _make_change(new="degraded", detail=None)
        result = generate_impact_statement(change, [])
        assert result.endswith("performance.")  # no trailing whitespace

    def test_empty_vendor_detail_whitespace(self):
        change = _make_change(new="degraded", detail="  ")
        result = generate_impact_statement(change, [])
        # Should strip cleanly
        assert not result.endswith(" ")


class TestGenerateSummaryText:
    def test_all_healthy(self):
        result = generate_summary_text(29, 0, [])
        assert "All 29" in result
        assert "operational" in result

    def test_with_incidents(self):
        result = generate_summary_text(29, 2, ["Identity Provider", "Chat Platform"])
        assert "2 active incident" in result
        assert "29" in result
        assert "Identity Provider" in result
        assert "Chat Platform" in result

    def test_single_incident(self):
        result = generate_summary_text(29, 1, ["Content Platform"])
        assert "1 active incident" in result
