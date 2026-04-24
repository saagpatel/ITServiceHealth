# Executive-View Redesign — Scoped Addendum

## Overview
This bundle redesigns the Executive-view codepath of the Pulse / IT Service Health dashboard so it reads from three meters in a conference room. It is an additive feature inside the existing React frontend — the Engineer view, backend, and polling pipeline are out of scope. The root `CLAUDE.md` at the repo root remains authoritative for everything outside this feature.

## Tech Stack (this feature only)
- React: 19.2 (existing)
- Vite: 8.0 + `@tailwindcss/vite` 4.2 (existing)
- Tailwind CSS: 4.2 — `@theme` token block in `frontend/src/styles/index.css`
- recharts: 3.8 — already in tree for `SlaChart`; reused by the 30-day trend strip
- lucide-react: 1.8 — icon set already in tree
- No new runtime deps. If a task appears to need one, stop and escalate.

## Development Conventions
- React components: PascalCase files, one component per file, under `frontend/src/components/executive/` for new surfaces and `frontend/src/views/` for the top-level view shell
- Hooks: kebab-case `use-*.js` under `frontend/src/hooks/`
- Design tokens: declared only in `@theme` inside `frontend/src/styles/index.css`; never hardcode hex in components
- No `any`-equivalent escapes — components accept typed props via JSDoc or default-shape destructuring
- Commits: conventional commits, e.g. `feat(exec-view): ...`, `style(tokens): ...`
- After every file change, re-read the diff before committing; follow the root repo's Done = Verify → Commit rule

## Current Phase
**Phase 0: Foundation (tokens, data hook, view shell)**
See IMPLEMENTATION-ROADMAP.md for full phase details.

## Key Decisions
| Decision | Choice | Why |
|----------|--------|-----|
| Color system | High-contrast dark theme; single `--color-accent-alarm` (alarm-red) reserved for `major_outage` and `degraded` only | Conference-room legibility; one eye-magnet so red means "act now" |
| Typography scale | 2× jumps: 14 / 28 / 56 / 112 px; weight contrast 400 vs 700 | Satisfies the 2×-hierarchy rule; readable at 3 m |
| Data shape | Compose `/api/summary`, `/api/services`, `/api/services/sla`, `/api/services/sla/history?days=30` in one hook `use-executive-data.js` | Keeps components dumb; one place to memoize derived KPIs |
| View integration | New `ExecutiveView.jsx` replaces the `CategorySummary` render branch inside `App.jsx` when `view === "executive"` | Matches existing `ViewContext` gating; no routing changes |
| Trend strip library | `recharts` `<AreaChart>` or `<LineChart>` reused from `SlaChart` pattern | No new bundle weight |

## Phase-Boundary Review
At the end of every phase, run `/ultrareview` before committing the phase-final code. Do not skip on phases that "feel small."

## Do NOT
- Do not add features not in the current phase of IMPLEMENTATION-ROADMAP.md.
- Do not touch the Engineer render path (`ServiceGrid`, `ServiceDetail`, `DependencyGraph`, `Timeline`). This feature only runs when `view === "executive"`.
- Do not introduce a second accent color or a gradient. `--color-accent-alarm` is the only eye-magnet; everything else is neutral surface + typography.
- Do not add runtime dependencies. recharts, lucide-react, tailwind 4, and date-fns are the complete palette.
