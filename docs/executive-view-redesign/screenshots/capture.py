"""Capture the Phase 3 production screenshots for the Executive view.

Output (both at 1920 x 1080):
  docs/executive-view-redesign/screenshots/exec-operational.png
  docs/executive-view-redesign/screenshots/exec-major.png

The operational shot reads from the live dev server. The major shot uses
playwright route interception to return a synthetic major-outage payload
— writing to the real DB would be invasive and the screenshot only needs
visual fidelity, not persistence. Interception is scoped to just the
four Executive-view endpoints; everything else passes through.

Prereqs: the frontend dev server runs at http://localhost:5174 and the
backend is reachable (Vite proxies /api). Playwright + chromium are
installed into the project venv.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

HERE = Path(__file__).parent
BASE_URL = "http://localhost:5174/"
VIEWPORT = {"width": 1920, "height": 1080}


def _envelope(data):
    return {"data": data, "error": None, "meta": None}


def _operational_summary(orig: dict) -> dict:
    """Force-heal any demo-data incidents so the operational shot is clean."""
    orig = dict(orig)
    orig["active_incidents"] = []
    orig["overall_status"] = "operational"
    orig["healthy_count"] = orig.get("total_services", 30)
    orig["degraded_count"] = 0
    orig["outage_count"] = 0
    return orig


def _operational_services(orig: dict) -> dict:
    orig = dict(orig)
    services = []
    for svc in orig.get("services", []):
        s = dict(svc)
        if s.get("current_status") != "operational":
            s["current_status"] = "operational"
            s["current_status_detail"] = None
        s["poller_health"] = "healthy"
        services.append(s)
    orig["services"] = services
    orig["healthy_count"] = len(services)
    orig["degraded_count"] = 0
    orig["outage_count"] = 0
    orig["unknown_count"] = 0
    return orig


def _major_summary(orig: dict) -> dict:
    """Inject Okta (major) + Zoom (degraded) incidents into /api/summary."""
    orig = dict(orig)
    # Find okta + zoom rows in the existing services list if available,
    # otherwise synthesise minimal service dicts.
    now_iso = "2026-04-24T12:00:00+00:00"
    okta = {
        "id": "okta",
        "display_name": "Okta SSO",
        "category": "identity",
        "current_status": "major_outage",
        "current_status_detail": "SSO login completely unavailable",
        "last_status_change_at": "2026-04-24T11:36:00+00:00",
        "poller_health": "healthy",
        "tier": "critical",
        "pending_status": None,
        "pending_status_count": 0,
        "pending_status_since": None,
    }
    zoom = {
        "id": "zoom",
        "display_name": "Zoom",
        "category": "collaboration",
        "current_status": "degraded",
        "current_status_detail": "Meeting start latency elevated",
        "last_status_change_at": "2026-04-24T11:49:00+00:00",
        "poller_health": "healthy",
        "tier": "high",
        "pending_status": None,
        "pending_status_count": 0,
        "pending_status_since": None,
    }
    orig["overall_status"] = "major_outage"
    orig["active_incidents"] = [
        {
            "service": okta,
            "impact_statement": (
                "SSO login completely unavailable — users cannot reach Box, "
                "Jira, or Salesforce"
            ),
            "affected_services": ["Box", "Jira", "Salesforce"],
            "started_at": okta["last_status_change_at"],
        },
        {
            "service": zoom,
            "impact_statement": (
                "Meeting start latency elevated · video dropouts reported in "
                "#it-help"
            ),
            "affected_services": [],
            "started_at": zoom["last_status_change_at"],
        },
    ]
    orig["degraded_count"] = 1
    orig["outage_count"] = 1
    orig["healthy_count"] = max(
        0,
        orig.get("total_services", 30) - 2 - orig.get("unknown_count", 0),
    )
    orig["last_poll_at"] = now_iso
    return orig


def _major_services(orig: dict) -> dict:
    orig = dict(orig)
    services = []
    for svc in orig.get("services", []):
        s = dict(svc)
        if s["id"] == "okta":
            s["current_status"] = "major_outage"
            s["current_status_detail"] = "SSO login completely unavailable"
            s["last_status_change_at"] = "2026-04-24T11:36:00+00:00"
        elif s["id"] == "zoom":
            s["current_status"] = "degraded"
            s["current_status_detail"] = "Meeting start latency elevated"
            s["last_status_change_at"] = "2026-04-24T11:49:00+00:00"
        else:
            s["current_status"] = "operational"
            s["current_status_detail"] = None
        s["poller_health"] = "healthy"
        services.append(s)
    orig["services"] = services
    orig["healthy_count"] = sum(
        1 for s in services if s["current_status"] == "operational"
    )
    orig["degraded_count"] = sum(
        1 for s in services if s["current_status"] == "degraded"
    )
    orig["outage_count"] = sum(
        1
        for s in services
        if s["current_status"] in ("partial_outage", "major_outage")
    )
    return orig


def _capture(variant: str, out: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT)

        # Prime localStorage so the app boots into Executive view.
        context.add_init_script(
            "try { localStorage.setItem('pulse-view-mode', 'executive'); } catch {}"
        )

        page = context.new_page()

        def route_handler(route: Route) -> None:
            url = route.request.url
            try:
                response = route.fetch()
                body = response.json()
            except Exception:
                route.continue_()
                return

            data = body.get("data", {})
            if url.endswith("/api/summary"):
                data = (
                    _major_summary(data)
                    if variant == "major"
                    else _operational_summary(data)
                )
            elif url.endswith("/api/services"):
                data = (
                    _major_services(data)
                    if variant == "major"
                    else _operational_services(data)
                )
            # SLA + history pass through; they drive the KPI tile + trend
            # strip from whatever the backend currently has.

            body["data"] = data
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(body),
            )

        page.route("**/api/summary", route_handler)
        page.route("**/api/services", route_handler)

        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_selector('[data-testid="executive-view"]', timeout=10_000)
        # Wait for the recharts Area to finish its first render.
        page.wait_for_selector(
            '[aria-label="30-day uptime trend"] svg .recharts-area-area',
            timeout=10_000,
        )
        # Let tooltips/clamp text settle.
        page.wait_for_timeout(600)

        page.screenshot(path=str(out), full_page=False)
        print(f"wrote {out}")
        browser.close()


if __name__ == "__main__":
    out_dir = HERE
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = {
        "operational": out_dir / "exec-operational.png",
        "major": out_dir / "exec-major.png",
    }

    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("both", "operational"):
        _capture("operational", targets["operational"])
    if which in ("both", "major"):
        _capture("major", targets["major"])
