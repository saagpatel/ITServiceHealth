# Executive-View Redesign — Scoped Addendum

## Overview
Redesigns the Executive-view codepath of the IT Service Health dashboard so it reads from three meters in a conference room. Additive feature inside the existing React frontend — Engineer view, backend, and polling pipeline are out of scope. The root `CLAUDE.md` at the repo root remains authoritative for everything outside this feature.

## Tech Stack (this feature only)
- React: 19.2 (existing)
- Vite: 8.0 + `@tailwindcss/vite` 4.2 (existing)
- Tailwind CSS: 4.2 — `@theme` token block in `frontend/src/styles/index.css`
- recharts: 3.8 — already in tree for `SlaChart`; reused by the 30-day trend strip
- lucide-react: 1.8 — icon set already in tree
- No new runtime deps. Stop and escalate if a task appears to need one.

## File Conventions
- New components: `frontend/src/components/executive/` (surfaces), `frontend/src/views/` (view shell)
- Hooks: kebab-case `use-*.js` under `frontend/src/hooks/`
- Design tokens: declare only in `@theme` inside `frontend/src/styles/index.css` — no hex values in components
- Props: type via JSDoc or default-shape destructuring — no `any`-equivalent escapes
- Commits: conventional commits, e.g. `feat(exec-view): ...`, `style(tokens): ...`

## Key Decisions
| Decision | Choice | Why |
|----------|--------|-----|
| Color system | High-contrast dark theme; single `--color-accent-alarm` (alarm-red) reserved for `major_outage` and `degraded` only | Conference-room legibility; one eye-magnet so red means "act now" |
| Typography scale | 2× jumps: 14 / 28 / 56 / 112 px; weight contrast 400 vs 700 | Satisfies the 2×-hierarchy rule; readable at 3 m |
| Data shape | Compose `/api/summary`, `/api/services`, `/api/services/sla`, `/api/services/sla/history?days=30` in one hook `use-executive-data.js` | Keeps components dumb; one place to memoize derived KPIs |
| View integration | New `ExecutiveView.jsx` replaces the `CategorySummary` render branch inside `App.jsx` when `view === "executive"` | Matches existing `ViewContext` gating; no routing changes |
| Trend strip library | `recharts` `<AreaChart>` or `<LineChart>` reused from `SlaChart` pattern | No new bundle weight |

## Scope Gates
- **Phase scope:** Implement only what IMPLEMENTATION-ROADMAP.md defines for the current phase. Work outside the active phase requires a discussion first.
- **Engineer render path:** `ServiceGrid`, `ServiceDetail`, `DependencyGraph`, `Timeline` are out of scope — this feature runs only when `view === "executive"`.
- **Accent colors:** `--color-accent-alarm` is the sole eye-magnet. Keep all other surfaces neutral; no second accent color, no gradients.
- **Runtime dependencies:** recharts, lucide-react, tailwind 4, and date-fns are the complete palette. Escalate before adding anything.

## Phase-Boundary Review
At the end of every phase, run `/code-review` on the branch diff before committing the phase-final code. Do not skip on phases that "feel small." (Note: `/ultrareview` referenced in earlier drafts does not exist; use `/code-review` instead.)
