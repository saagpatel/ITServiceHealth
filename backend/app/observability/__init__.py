"""Phase 3 observability: metrics, Sentry, dead-man's switch, heartbeat.

Sibling modules:
  - metrics.py        — Prometheus counters/histograms/gauges definitions
  - sentry_setup.py   — Sentry init + secret-scrubbing before_send
  - heartbeat.py      — dead-man's switch + /healthz health endpoint
"""
