# IT Service Health Dashboard — Portfolio Disposition

**Status:** Active (self-hosted service) — Python + FastAPI + SQLite
+ React production IT-service status monitoring dashboard for ~30
SaaS services used by Enterprise IT on `origin/main`. **v1 (demo-ready)
SHIPPED. v2 (production-ready) SHIPPED through Phase 6 + most of
Phase 7. 356 tests passing.** Active Phase 7 cadence in flight
(postmortem automation, SLO views, multi-burn-rate alerting,
`/itstatus` slash command bot — all shipped in recent merges).
**Second member of the self-hosted service cluster** after
RedditSentimentAnalyzer. Distinct from RSA: this is a **corporate-
context self-hosted service** (operator's employer, not personal
infrastructure).

> Disposition uses strict `origin/main` verification.
> **Stabilizes self-hosted service cluster at 2 members with
> corporate-context sub-shape.**

---

## Verification posture

Only `origin` (`saagpatel/ITServiceHealth`). Clean migration state.
**Working tree clean** (`git status --short` returned empty).

`origin/main`:

- Tip: `cc15c9a` perf(logging): offload file I/O to QueueListener
  thread (#28)
- **Active Phase 7 cadence** (last 6 PRs all merged):
  - `cc15c9a` perf(logging): QueueListener for file I/O (#28)
  - `4932246` feat(alerting): vendor_incident_id extraction +
    per-service webhook override (#27)
  - `b0653bc` feat(slack): /itstatus slash command bot (Phase 7
    item 4) (#26)
  - `fc7777c` feat(slo): fuel-gauge view + /api/services/slo
    endpoint (Phase 7 item 3) (#25)
  - `79eb908` feat(alerting): multi-burn-rate SLO alerting (Phase
    7 item 2) (#24)
  - `41f5cab` feat(postmortems): Google-SRE-style Markdown drafts
    on incident recovery (#23)
- v2 production hardening (already shipped):
  - Bearer-token auth, vendor resilience (stamina + purgatory),
    flap suppression, dedup, tier routing, dependency correlation,
    maintenance windows, observability (structlog + Prometheus
    `/metrics` + Sentry + Healthchecks.io dead-man's switch),
    Litestream streaming + daily `VACUUM INTO` snapshot, PWA,
    hardened launchd plist, Caddy reverse proxy, Keychain secrets
- **356 tests passing**
- `PRODUCTION-ROADMAP.md` + `IMPLEMENTATION-ROADMAP.md` on
  canonical main
- Default branch: `main`

---

## Current state in one paragraph

IT Service Health Dashboard is a Python + FastAPI + SQLite + React
real-time status monitoring dashboard for **~30 SaaS services used
in an enterprise IT environment** (the operator's employer). The pipeline: **async pollers
hit vendor status APIs every 60 seconds** (Statuspage.io for 15
services, chat-platform Status API for 1, cloud-productivity-suite JSON feed for 2,
manual `POST /api/admin/status` for the remaining 11) → **status
normalizer** maps to 5-state enum (operational / degraded / partial /
major / unknown) → **change detector** diffs against SQLite, writes
status_events → **impact statement engine** uses a dependency
graph + templates to generate human-readable impact → **Slack
alerter** posts Block Kit messages to the ops-alert channel →
**FastAPI REST** + **React dashboard** auto-refreshes every 30
seconds. **v1 fully shipped (demo-ready). v2 fully shipped through
Phase 6 (production-ready). Phase 7 actively in flight** (postmortem
automation + SLO views + multi-burn-rate alerting + Slack slash
command + per-service webhook overrides all shipped in the last
6 merges). **356 tests passing.** Phase 2B + Phase 7 webhooks
(Statuspage inbound + Slack ack) are gated off pending a public
reachability path (Cloudflare Tunnel / Caddy allowlist).

---

## Why "Active (self-hosted service)" — second cluster member, corporate context

Joins **self-hosted service cluster** as the second member.
RedditSentimentAnalyzer (R10) founded the cluster with personal
self-hosted infrastructure (launchd + nginx). ITServiceHealth
extends:

| Aspect | RedditSentimentAnalyzer | **ITServiceHealth** |
|---|---|---|
| Audience | Operator-personal | **Operator's employer (enterprise IT)** |
| Reachability | launchd + nginx | **launchd + Caddy + Cloudflare Tunnel (planned)** |
| Secrets | Standard | **macOS Keychain** |
| Observability | Basic | **structlog + Prometheus `/metrics` + Sentry + Healthchecks.io dead-man's switch** |
| Data lifecycle | Standard SQLite | **Litestream streaming + daily VACUUM INTO snapshot** |
| Alerting | Reddit polling | **5-state vendor polling + Slack Block Kit + dependency-graph impact statements** |

This is **enterprise-grade self-hosted service** — substantially
more operational maturity than RSA's pattern. Introduces sub-shape:
**corporate-context self-hosted service** (vs personal self-hosted).

State is **Active** because:
- Phase 7 is actively shipping (postmortems, SLO views, slash
  command bot, multi-burn-rate alerting all in the last 6 merges)
- Phase 7 remainder is operator-cadence (postmortem automation
  variants, SLO views, multi-burn-rate alerting all shipped;
  Slack slash command shipped; remainder is optional polish)
- Phase 2B webhooks are gated off, awaiting public reachability

If Phase 7 completes and the operator declares no further roadmap,
this transitions to Release Frozen (self-hosted service,
production).

---

## Cluster taxonomy update

| Cluster | Count | Sub-shapes |
|---|---|---|
| **Self-hosted service** | **2** | personal (RedditSentimentAnalyzer) / **corporate-context (ITServiceHealth)** |
| (others unchanged) | | |

Self-hosted service cluster reaches 2 members with sub-shape
structure (matches operator-tool's pure / multi-surface pattern).

---

## Unblock trigger (operator)

This is already in production for the operator's employer.
Operational concerns:

1. **Phase 2B + Phase 7 webhooks reachability** — Statuspage
   inbound webhook receiver + Slack ack flow shipped with HMAC
   verification but gated off. Flip when Cloudflare Tunnel or
   Caddy allowlist is in place.
2. **Phase 7 remainder polish** — postmortem variants, SLO views,
   multi-burn-rate alerting all shipped; remainder is operator-
   cadence demand-driven.
3. **Vendor status API breakage monitoring** — Statuspage.io and
   the chat-platform Status API are stable but the cloud productivity suite JSON feed has
   changed format historically; observability via
   Healthchecks.io dead-man's switch catches silent breakage.
4. **Litestream snapshot verification** — daily `VACUUM INTO`
   provides recovery; verify restore path periodically.
5. **Keychain secret rotation** — bearer tokens + Slack
   credentials + Sentry DSN + vendor API keys all in Keychain;
   document rotation cadence.
6. **launchd plist hardening + Caddy config** verification on
   major macOS updates.

No public unblock — this serves the operator's employer
internally.

---

## Portfolio operating system instructions

| Aspect | Posture |
|---|---|
| Portfolio status | `Active (self-hosted service, corporate-context)` |
| Audience | **Enterprise IT** (operator's employer) |
| Distribution model | **Self-hosted on operator infrastructure** (launchd + Caddy + Cloudflare Tunnel) |
| Review cadence | Active — Phase 7 polish + Phase 2B gating + operational maintenance |
| Resurface conditions | (a) Phase 2B webhook gating decision, (b) vendor API breakage, (c) macOS update breaks launchd or Caddy, (d) Keychain secret rotation cadence, (e) v3 scope packet |
| Co-batch with | Self-hosted service cluster — **now 2 repos** (personal + corporate-context) |
| Sub-shape | **Corporate-context self-hosted service** (new) |
| Special concern | **Vendor status API breakage monitoring.** Healthchecks.io dead-man's switch is the load-bearing observability layer. |
| Special concern | **Phase 2B webhook reachability** — gated off until Cloudflare Tunnel or Caddy allowlist in place. |
| Special concern | **Litestream + VACUUM INTO snapshot** — verify restore path periodically. |
| Special concern | **Corporate context** — operator's employer relies on this; ship discipline higher than personal projects. |

---

## Reactivation procedure

1. Verify branch tracking.
2. Working tree clean — no stash needed.
3. **Re-read `PRODUCTION-ROADMAP.md`** for current Phase 7 state.
4. Run `pytest` — expect 356 tests passing.
5. Verify launchd plist + Caddy config still functional.
6. Verify Healthchecks.io dead-man's switch is being pinged.
7. Check Litestream stream + most recent daily snapshot.
8. Verify vendor status API integrations (Statuspage / chat platform /
   cloud productivity suite) are still parsing correctly.

---

## Last known reference

| Field | Value |
|---|---|
| `origin/main` tip | `cc15c9a` perf(logging): offload file I/O to QueueListener thread (#28) |
| Last substantive feat | `4932246` feat(alerting): vendor_incident_id extraction + per-service webhook override (#27) |
| Default branch | `main` |
| Build system | Python + FastAPI + SQLite + React + Caddy reverse proxy + launchd + macOS Keychain |
| Service count | ~30 SaaS services monitored |
| Test count | **276 tests passing** |
| Audience | **Enterprise IT (operator's employer)** — corporate-context self-hosted |
| Phases shipped | v1 demo-ready + v2 production-ready Phases 0-6 + Phase 7 items 1-4 (postmortems + SLO views + multi-burn-rate alerting + /itstatus slash command) |
| Observability stack | structlog + Prometheus `/metrics` + Sentry + Healthchecks.io dead-man's switch |
| Data lifecycle | Litestream streaming + daily `VACUUM INTO` snapshot |
| Active arc | Phase 7 polish + Phase 2B webhook gating |
| Migration state | No `legacy-origin` remote |
| Distinguishing feature | **Second self-hosted service cluster member; introduces corporate-context sub-shape.** Substantially more operational maturity than RedditSentimentAnalyzer (Keychain + Litestream + Caddy + observability stack). Active Phase 7 cadence. |
