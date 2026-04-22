"""Prometheus metrics definitions.

Every metric is module-level and lives in the default global registry.
Single-process app, single-process registry — no multiprocess gymnastics.

Exposed via the `/metrics` endpoint mounted in main.py. A Prometheus
scraper (or `curl /metrics`) gets:

  - poll_duration_seconds{service}     — histogram, per-service wall time
  - poll_total{service,outcome}        — counter (ok | timeout | http_error | parse_error | circuit_open)
  - service_status{service}            — gauge, 0=operational, 1=degraded, 2=partial, 3=major, 4=unknown
  - poller_health_state{service}       — gauge, 0=healthy, 1=degraded, 2=broken
  - alerts_sent_total{kind,severity}   — counter (fired alerts)
  - alerts_suppressed_total{kind,reason} — counter (suppressed alerts, by suppression reason)
  - circuit_breaker_state{host}        — gauge, 0=closed, 1=open, 2=half-open
  - scheduler_last_heartbeat_seconds   — gauge, wall-clock seconds since last heartbeat
  - poll_cycles_total{outcome}         — counter (completed | errored)

All series have bounded cardinality — labels are service_id, host,
outcome enum, or alert kind/severity enum.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

POLL_DURATION_SECONDS = Histogram(
    "poll_duration_seconds",
    "Wall-clock time spent in a single poller function call. Labeled by "
    "poll_type because batch pollers (statuspage, google) share one HTTP "
    "fetch across several services.",
    ["poll_type"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

POLL_TOTAL = Counter(
    "poll_total",
    "Per-service poll outcomes, extracted from each PollResult during "
    "change detection. Outcome is 'ok' on success or the mechanical "
    "failure category (timeout, http_5xx, http_4xx, circuit_open, etc.).",
    ["service", "outcome"],
)


def outcome_from_failure_reason(reason: str | None) -> str:
    """Map the mechanical poll_failure_reason into a low-cardinality bucket."""
    if reason is None:
        return "ok"
    if reason.startswith("circuit_breaker_open"):
        return "circuit_open"
    if reason == "timeout":
        return "timeout"
    if reason.startswith("http_5") or reason.startswith("transient_http_5"):
        return "http_5xx"
    if reason.startswith("http_4") or reason.startswith("transient_http_4"):
        return "http_4xx"
    if reason.startswith("request_error"):
        return "request_error"
    if reason.startswith("parse_error"):
        return "parse_error"
    return "other"

SERVICE_STATUS = Gauge(
    "service_status",
    "Current normalized status for each service "
    "(0=operational, 1=degraded, 2=partial_outage, 3=major_outage, 4=unknown).",
    ["service"],
)

POLLER_HEALTH_STATE = Gauge(
    "poller_health_state",
    "Per-service poller health (0=healthy, 1=degraded, 2=broken).",
    ["service"],
)

ALERTS_SENT_TOTAL = Counter(
    "alerts_sent_total",
    "Alerts actually delivered to Slack, by kind and severity.",
    ["kind", "severity"],
)

ALERTS_SUPPRESSED_TOTAL = Counter(
    "alerts_suppressed_total",
    "Alerts suppressed by the routing pipeline, by reason.",
    ["kind", "reason"],
)

CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state",
    "Per-host circuit breaker state (0=closed, 1=open, 2=half_open).",
    ["host"],
)

SCHEDULER_LAST_HEARTBEAT_SECONDS = Gauge(
    "scheduler_last_heartbeat_seconds",
    "Seconds elapsed since the scheduler last wrote a heartbeat. "
    "Values >120 are treated as unhealthy by /healthz.",
)

POLL_CYCLES_TOTAL = Counter(
    "poll_cycles_total",
    "Completed scheduler poll cycles, by outcome (completed | errored).",
    ["outcome"],
)


# ── Human-readable label values ─────────────────────────────────────

STATUS_VALUE = {
    "operational": 0,
    "degraded": 1,
    "partial_outage": 2,
    "major_outage": 3,
    "unknown": 4,
}

POLLER_HEALTH_VALUE = {
    "healthy": 0,
    "degraded": 1,
    "broken": 2,
}

BREAKER_STATE_VALUE = {
    "closed": 0,
    "opened": 1,
    "half_opened": 2,
}


def record_service_status(service_id: str, status: str) -> None:
    value = STATUS_VALUE.get(status, STATUS_VALUE["unknown"])
    SERVICE_STATUS.labels(service=service_id).set(value)


def record_poller_health(service_id: str, health: str) -> None:
    value = POLLER_HEALTH_VALUE.get(health, 0)
    POLLER_HEALTH_STATE.labels(service=service_id).set(value)


def record_circuit_breaker_state(host: str, state: str) -> None:
    value = BREAKER_STATE_VALUE.get(state, 0)
    CIRCUIT_BREAKER_STATE.labels(host=host).set(value)
