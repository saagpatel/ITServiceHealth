# 3 steps to a Claude Design reskin

Claude Design reads the Pulse repo directly — **you don't need screenshots** for it to understand the UI. Skip this whole step unless you want to show it a specific visual state (like what "flapping" looks like live).

---

## Step 1 — Start Claude Design

1. Open **[claude.ai/design](https://claude.ai/design)** → **New Project** → name it "Pulse redesign"
2. Link the repo: `https://github.com/saagpatel/ITServiceHealth`
3. Upload this folder (just drag `docs/design-brief/` onto the project)

## Step 2 — Paste this as your first message

> Read `docs/design-brief/brief.md` first — audiences, non-negotiables, and direction. Then read `design-system-export.md` for the tokens + semantic rules you must preserve and `component-inventory.md` for the surface list.
>
> Propose a full visual direction: palette, typography, spacing scale, and how the five status colors land in your new palette. Include a "how this feels different from today" paragraph. Don't touch individual components yet — I want to approve the direction first.

Iterate until you like it. Then ask for per-surface proposals:
> Good. Now produce each surface from component-inventory.md. Engineer-mode grid first.

## Step 3 — Hand off to Claude Code

When Claude Design is happy, click **Handoff to Claude Code**. Open a **new Claude Code chat** in this repo and paste:

> Apply this Claude Design handoff bundle to Pulse. Base branch is main, target branch `feat/claude-design-refresh`. Split into two PRs: tokens-only first (`@theme` + fonts), then per-component Tailwind tuning. Before each PR, verify `npm run build`, `npx eslint src/`, and that every non-negotiable from `docs/design-brief/design-system-export.md` survives.
>
> [paste the bundle here]

I'll apply it, verify, open the PRs. You review the preview, approve or send notes.

---

## Optional: grab screenshots

Only needed if you want to show Claude Design a specific live state it can't derive from code (flapping, poller-broken, active incident). The app is already running at **[localhost:8000](http://localhost:8000)**.

1. Press **Cmd+Shift+4**, **Space**, click the Chrome window → saves to Desktop
2. Drop into `docs/design-brief/screenshots/`
3. Toggle Executive / Engineer with the header pill; repeat for both
4. To simulate a degraded state for a screenshot:
   ```bash
   curl -X POST http://localhost:8000/api/admin/status \
     -H "Authorization: Bearer $ADMIN_API_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"service_id":"identity-provider","new_status":"major_outage","reason":"screenshot"}'
   ```
   Revert:
   ```bash
   curl -X POST http://localhost:8000/api/admin/status \
     -H "Authorization: Bearer $ADMIN_API_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"service_id":"identity-provider","new_status":"operational","reason":"revert"}'
   ```
