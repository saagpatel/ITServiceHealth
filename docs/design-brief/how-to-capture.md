# Capture + Handoff Guide

Step-by-step for getting Pulse into Claude Design and back out as a code bundle.

## Part 1 — Get the app running locally

```bash
# From repo root
source .venv/bin/activate
cd backend && python run.py
```

Open [http://localhost:8000](http://localhost:8000). You should see the dashboard with ~26 services, Engineer view by default.

If the backend has nothing to render (fresh DB), seed demo data first:
```bash
cd backend && python -m scripts.seed_demo_data
```

## Part 2 — Capture screenshots

Save each into [`./screenshots/`](./screenshots/) with the filename shown. Claude Design reads images better when they're full-viewport (not cropped).

**Recommended size:** `1440×900` (desktop) for the main shots; `375×812` (mobile) for the responsive check.

### Engineer view

1. `01-engineer-full.png` — default load, nothing degraded (or fresh seed)
2. `02-engineer-with-incidents.png` — while at least one service is `degraded` or worse. If nothing is live, manually set a service via:
   ```bash
   curl -X POST http://localhost:8000/api/admin/status \
     -H "Authorization: Bearer $ADMIN_API_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"service_id":"okta","new_status":"major_outage","detail":"SSO down","reason":"screenshot capture"}'
   ```
3. `03-engineer-tile-hover.png` — hover state on a tile
4. `04-engineer-service-drawer.png` — click a tile, capture the right-side detail drawer open
5. `05-engineer-dependency-graph.png` — press `g`, capture the full overlay
6. `06-engineer-timeline.png` — scroll to the Timeline section
7. `07-engineer-shortcuts.png` — press `?`, capture overlay
8. `08-engineer-poller-broken.png` — if a poller is naturally broken you'll see a dashed tile; otherwise skip. (Don't fake it — the treatment is already documented in `design-system-export.md`.)
9. `09-engineer-flapping.png` — same: if a service is actively flapping you'll see the yellow Activity badge in the top-right. Skip if nothing is flapping.

### Executive view

Click the view toggle in the header (or flip `view` via the ViewToggle segmented control).

10. `10-executive-full.png` — default Executive view
11. `11-executive-with-incidents.png` — same incident state as shot #2
12. `12-executive-category-hover.png` — hover on a category card

### Mobile

13. `13-mobile-engineer.png` — browser window resized to 375×812, Engineer view
14. `14-mobile-executive.png` — same size, Executive view

### Revert any test state

If you set a service to `major_outage` for the screenshots, revert it:
```bash
curl -X POST http://localhost:8000/api/admin/status \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"service_id":"okta","new_status":"operational","reason":"revert screenshot test"}'
```

## Part 3 — Feed Claude Design

Open [Claude Design](https://claude.ai/design). Start a new project titled "Pulse redesign".

**Upload / link in this order:**

1. [`brief.md`](./brief.md) — primary intent
2. [`design-system-export.md`](./design-system-export.md) — current tokens + semantic rules
3. [`component-inventory.md`](./component-inventory.md) — surface list
4. The `screenshots/` folder contents
5. Link the repo: `https://github.com/saagpatel/ITServiceHealth` — Claude Design can pull the actual source to understand structure. If the repo is private, upload the `frontend/` directory instead.

**First prompt to Claude Design:**

> I want to redesign Pulse, an internal IT service-health dashboard. Read `brief.md` first — it explains the audiences, non-negotiables, and direction. Then read `design-system-export.md` for the current tokens + semantic rules you must preserve. `component-inventory.md` lists every surface that needs a treatment. Screenshots show the current state.
>
> Start by proposing a full visual direction: palette, typography, spacing scale, and how the five status colors land in your new palette. Include a "how this feels different from today" paragraph. Don't touch individual components yet — I want to approve the direction first.

**Iterate.** Push back on anything that breaks a non-negotiable. Particularly watch for:
- Status colors being dulled past the point of at-a-glance severity ramp
- Poller-broken state losing its distinct visual
- Executive mode slipping into "landing page" / marketing aesthetic

Once direction lands, ask for per-surface proposals:
> Good. Now produce each surface from component-inventory.md. Engineer-mode grid first.

## Part 4 — Get the handoff bundle

When you're happy, use Claude Design's **"Handoff to Claude Code"** feature. It produces a bundle — typically a single markdown instruction containing:
- Updated CSS `@theme` block
- Per-component Tailwind class changes
- Any new font imports / asset URLs
- Rationale for changes

Save that bundle as `handoff-bundle.md` in a new chat with Claude Code, and say:

> Apply the Claude Design handoff bundle in handoff-bundle.md to Pulse. Base branch is `main`. Open a PR against main named `feat/claude-design-refresh`. Before PRing, verify: npm run build, npx eslint src/, pytest, and that all non-negotiables from docs/design-brief/design-system-export.md survive.

I'll apply it, verify, preview the diff, and open the PR.

## Part 5 — Review + merge

I'll post the PR link + a list of the non-negotiables and how each one survived. You review in the PR preview (or pull the branch + `npm run dev`). Approve or send corrections; I iterate.

## A note on scope

The safest split is a **two-PR adoption**:
1. **Tokens-only PR:** just the `@theme` block, fonts, and global CSS. This reskins every surface at once via CSS variables — low risk, easy to roll back.
2. **Component-tuning PR:** per-component Tailwind class updates where the tokens alone don't capture the direction (e.g., new tile shape, drawer chrome).

If Claude Design's first proposal is ambitious enough that both PRs would collide, tell it to produce the tokens-only bundle first.
