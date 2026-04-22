# Pulse — Claude Design Brief

This directory is the handoff package for [Claude Design](https://www.anthropic.com/news/claude-design-anthropic-labs). Point Claude Design at this folder (or at the repo root) to produce a redesigned visual system that we then bring back through the Claude Design → Claude Code handoff bundle.

## What's in here

| File | For Claude Design | For you |
|------|-------------------|---------|
| [`brief.md`](./brief.md) | The product intent, audiences, and non-negotiables. Read this first. | |
| [`design-system-export.md`](./design-system-export.md) | Current tokens + components in machine-readable form. | |
| [`component-inventory.md`](./component-inventory.md) | Every React component + its role in the UI. | |
| [`how-to-capture.md`](./how-to-capture.md) | | Step-by-step: start the app, grab screenshots, feed Claude Design, bring the handoff back. |
| [`screenshots/`](./screenshots/) | | You drop screenshots here before starting Claude Design. |

## The two-surface workflow

```
┌──────────────────────────┐       ┌────────────────────────┐
│  Claude Design (web)     │       │  Claude Code (here)    │
│  — reads this folder     │       │  — applies the bundle  │
│  — reads repo codebase   │       │    to frontend/src/    │
│  — produces visual       │       │  — PR + verify + merge │
│    proposal + handoff    │──────▶│                        │
│    bundle                │       │                        │
└──────────────────────────┘       └────────────────────────┘
```

1. **In Claude Design:** upload or link this folder + the repo. Iterate on the visual direction. Export the **handoff to Claude Code** bundle.
2. **Back in Claude Code:** paste the bundle into a new chat with me; I'll apply it to `frontend/src/`, run `npm run build`, open a preview PR.

## Why this brief exists

Pulse is already WCAG-accessible, dense, and tuned for two different audiences (IT engineers vs. IT leadership). A redesign that looks pretty but breaks that tuning is a regression, not a refresh. This brief makes the non-negotiables explicit so Claude Design's output lands as a drop-in upgrade instead of a do-over.
