# Pulse — Design Brief

## What Pulse is

An internal status dashboard that aggregates real-time health of ~30 SaaS services used by Enterprise IT (identity, collaboration, productivity, CRM, video, telephony, and ITSM tools). Polls vendor status endpoints every 60 seconds, detects state changes, fires Slack alerts, renders a unified board with timeline + dependency graph + SLA history. Served from a Mac Mini on the internal network at `http://<host>:8000`.

## Who uses it

| Audience | View | Why they open it |
|----------|------|------------------|
| **IT engineers (on-call)** | Engineer mode | At-a-glance triage: what's broken right now, what's flapping, what depends on what. They need density — fits on one screen, readable at 3AM. |
| **IT leadership / exec** | Executive mode | Situational awareness: "Is anything on fire this morning?" They do not want to parse 30 tiles. Category-level rollups + SLA trends. |
| **Company-wide (read-only)** | Either | Linked from the IT intranet page so anyone can self-serve. No login — VPN is the security boundary. |

## Primary jobs-to-be-done

1. **"Is the identity provider down?"** — a sub-5-second glance that answers the single most common question the IT helpdesk gets asked.
2. **"What's the blast radius?"** — if something is degraded, what depends on it? (Dependency graph + impact statements.)
3. **"Has this been flapping?"** — the backend's flap-suppression state machine is visible; operators need to see "we've seen 2 bad polls in a row, one more and we'll fire."
4. **"What's our 30-day uptime on the HR system?"** — for leadership reporting + vendor renewal conversations.
5. **"Who acknowledged the Slack alert?"** — once the ack flow is live, the dashboard should reflect that someone owns it.

## Design direction

We're aiming for a **Claude-leaning treatment**: warmer, quieter, more editorial than the current dark ops-console theme. The current look serves engineers well but feels cold to leadership and intimidating to company-wide viewers. Think "thoughtful product surface" rather than "NOC wall."

**Desirable qualities (Claude-ish):**
- Warm neutrals over pure dark. Off-white, ivory, or a soft charcoal rather than `#0b1120` slate.
- Typography with personality — something like Styrene/Tiempos-ish rather than IBM Plex. Editorial serif for headlines is on the table for Executive view only; Engineer stays sans.
- Generous whitespace where it doesn't compromise density. Engineer stays tight; Executive breathes more.
- Subtle restraint in color: status colors stay vivid because they're semantic, but chrome/borders/backgrounds get quieter.
- Soft radii, gentle shadows, no harsh gradient accents.

**Undesirable (explicit):**
- No purple-gradient "AI-flavored" looks. This is an operations tool, not a landing page.
- No skeuomorphic NOC chrome (glowing CRT lines, terminal frames).
- No bright hero-banner treatment of incident state — severity needs to ramp visibly, not shout.

## Non-negotiables (these must survive any redesign)

### Status semantics — WCAG 1.4.1

Every status must be distinguishable by **shape + color + label**, not color alone. The current system does this with Lucide icons (`CheckCircle2`, `AlertTriangle`, `AlertOctagon`, `XOctagon`, `HelpCircle`, `WifiOff`). A redesign can swap icons but must preserve the three-channel redundancy.

Five status states must be visually rankable worst-to-best: `major_outage > partial_outage > degraded > unknown > operational`.

### Poller-broken state

A service whose poller is broken renders as `unknown` with a **visually distinct "we're blind" treatment** — currently a dashed border + `WifiOff` icon. This is the single most important UX invariant: *never* render `operational` when the poller has failed. A healthy-looking tile that's actually stale is worse than no tile.

### Flapping-unstable badge

Services that are mid-flap (backend's `pending_status != current_status`) show a small "unstable" indicator distinct from the committed status. Currently a yellow `Activity` icon in the top-right of the tile.

### Severity sort

The grid sorts worst-first, per-category. Categories themselves sort worst-first. Leadership should never have to scan for the one red tile. This ordering logic stays; only the visual can change.

### Accessibility

- All interactive elements have visible `:focus-visible` rings (currently 2px accent with 2px offset).
- Full keyboard navigation: `j`/`k`/arrows to walk the grid, `Enter` to open detail, `g` to open dependency graph, `Esc` to close, `?` for shortcuts.
- `prefers-reduced-motion` disables animations.
- A `role="status" aria-live="polite"` region announces high-level state changes; tiles do NOT announce individually (spam).

### Density (Engineer mode only)

Engineer mode sees ~30 tiles in a 4-column grid on desktop, 3 on tablet, 2 on mobile. Tiles are ~72px tall today. Density can shift modestly (60–100px range) but a redesign that halves the count per viewport is a regression.

### Executive mode breathing room

Executive sees category rollups, not individual tiles. This view *should* feel calmer. Aim for 6–8 cards max in viewport, with real margin + a clear "all ok" default state.

## Views and surfaces

Claude Design should produce proposals for each:

1. **Header bar** — Pulse wordmark, view toggle, stale-since indicator, keyboard-shortcuts button. Currently dense + monospace-feeling.
2. **Status banner** — the headline state (all ok / N incidents active). Currently a single colored pill; leadership is the target.
3. **Active-incidents section** — list of currently-affected services with impact statements. Executive: only show critical; Engineer: show all.
4. **Service grid (Engineer)** — the 4-column tile grid with severity sort, poller-broken dashed border, flapping badge.
5. **Category summary (Executive)** — one card per service category with rollup health + SLA trend.
6. **Service-detail drawer** — slides in from right when a tile is clicked. Shows dependencies, recent events, SLA history (`recharts` line chart).
7. **Timeline section (Engineer only)** — clustered status-change events over the past N hours.
8. **Dependency graph overlay (Engineer only)** — force-directed graph showing service deps; toggle with `g`.
9. **Maintenance banner** — upcoming vendor maintenance windows.
10. **Error banner** — aggregates fetch failures from the frontend's own API calls.
11. **Shortcuts overlay** — keyboard help, toggle with `?`.
12. **Reload prompt (PWA)** — service-worker update available.

## Tech constraints for the handoff

- **React 19 + Vite + Tailwind 4** — Tailwind is v4 syntax (`@theme`, not `tailwind.config.js`). Handoff CSS variables map cleanly to `@theme` tokens.
- **IBM Plex via `@fontsource`** self-hosted — no CDN fonts (deploy is internal-network-only). If the new typography is a commercial/Google font, we need a self-hostable equivalent or a Fontsource package.
- **Lucide icons** — easy to keep or swap.
- **`recharts`** for SLA trend — any chart restyling should fit inside recharts' props, not require migration.
- **No new component framework** — we're not adopting shadcn/ui or MUI just for this refresh. Tailwind + plain React components only.

## Out of scope for this redesign

- Changing the information architecture (which surfaces exist, what each one shows).
- Adding new data — everything Claude Design proposes should fit the existing API shape (see `backend/app/router_*.py`).
- Rewriting the dependency graph engine (we use `react-force-graph-2d`; keep it).
- Rebuilding the service worker or PWA flow.

## Success criteria

A redesign lands when:
1. Executive mode feels meaningfully calmer + more editorial; leadership says "this looks good" without being asked to squint.
2. Engineer mode remains fast at-a-glance triage; on-call engineers don't lose ~any seconds-to-diagnosis.
3. All five non-negotiables above are visibly intact.
4. `npm run build` + `npx eslint src/` + `pytest` all still green.
5. The PWA service worker still precaches + updates correctly.
