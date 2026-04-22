# Pulse — Current Design System Export

This is the source-of-truth extraction of every visual token + semantic rule Pulse uses today. Claude Design should **preserve the semantics** (status → color meaning, severity rank, poller-broken treatment) and is free to reinterpret the **visual expression** (what those colors actually look like, typography, spacing).

## Source files

| Token type | Defined in |
|------------|------------|
| Tailwind theme (CSS variables) | [`frontend/src/styles/index.css`](../../frontend/src/styles/index.css) — uses Tailwind 4 `@theme` directive |
| Semantic status tokens (colors, tints, icons, labels, sort rank) | [`frontend/src/lib/constants.js`](../../frontend/src/lib/constants.js) |
| Fonts | Self-hosted via `@fontsource/ibm-plex-sans` + `@fontsource/ibm-plex-mono` |

## Tailwind `@theme` tokens (current dark theme)

```css
@theme {
  /* Status semantics — vivid, because they carry meaning */
  --color-status-operational: #34d399;   /* emerald-400 */
  --color-status-degraded:    #fbbf24;   /* amber-400  */
  --color-status-partial:     #fb923c;   /* orange-400 */
  --color-status-major:       #f87171;   /* red-400    */
  --color-status-unknown:     #6b7280;   /* gray-500   */

  /* Chrome — quiet, supporting */
  --color-bg-page:       #0b1120;   /* near-black slate */
  --color-bg-surface:    #151d2e;
  --color-bg-hover:      #1e293b;
  --color-border:        #1e293b;
  --color-text-primary:  #f1f5f9;
  --color-text-secondary:#94a3b8;
  --color-text-muted:    #64748b;
  --color-accent:        #38bdf8;   /* sky-400 — focus rings, links */

  /* Banner backgrounds (tonal chrome for status banner variants) */
  --color-banner-ok:   #064e3b;
  --color-banner-warn: #78350f;
  --color-banner-crit: #7f1d1d;

  --font-sans: "IBM Plex Sans", ui-sans-serif, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
}
```

## Status color language (semantic — do not break)

| Status key | Hex | Label | Icon | Severity rank |
|------------|-----|-------|------|---------------|
| `major_outage`   | `#f87171` | "Major Outage"   | `XOctagon`     | 4 (worst) |
| `partial_outage` | `#fb923c` | "Partial Outage" | `AlertOctagon` | 3 |
| `degraded`       | `#fbbf24` | "Degraded"       | `AlertTriangle`| 2 |
| `unknown`        | `#6b7280` | "Unknown"        | `HelpCircle`   | 1 |
| `operational`    | `#34d399` | "Operational"    | `CheckCircle2` | 0 (best) |

**Shape + color + label must all disambiguate** — WCAG 1.4.1. A colorblind operator must be able to tell `degraded` from `partial_outage` without seeing color.

## Tile background tints

```js
STATUS_TINTS = {
  operational:   "rgba(52, 211, 153, 0.15)",
  degraded:      "rgba(251, 191, 36, 0.18)",
  partial_outage:"rgba(251, 146, 60, 0.18)",
  major_outage:  "rgba(248, 113, 113, 0.20)",
  unknown:       "rgba(107, 114, 128, 0.08)",
};

STATUS_TINTS_HOVER = {
  operational:   "rgba(52, 211, 153, 0.25)",
  degraded:      "rgba(251, 191, 36, 0.30)",
  partial_outage:"rgba(251, 146, 60, 0.30)",
  major_outage:  "rgba(248, 113, 113, 0.32)",
  unknown:       "rgba(107, 114, 128, 0.15)",
};
```

Severity is encoded in tint density — worse → more saturated. Hover deepens ~10%.

## Special visual states (semantic — do not break)

### Poller broken

When `service.poller_health === "broken"`:
- Tile uses **dashed border** (currently `border-dashed` via Tailwind, 3px left border)
- Icon overridden to `WifiOff`
- Label forced to "Unknown"
- Tooltip: "Poller broken — readings may be stale"

Rule: *Never* render `operational` when the poller is broken. `effectiveStatus(svc)` forces `unknown` in this case.

### Flapping / unstable

When `service.pending_status && service.pending_status !== service.current_status`:
- Small `Activity` icon + pending status label in tile's top-right corner
- Color `#fbbf24` (reuses degraded yellow — yellow already means "watch this")
- Animates via `motion-safe:animate-pulse` only
- Replaces the uptime-percent chip when both would fight for space

### Unmonitored (manual service, never updated)

- Tile opacity dropped to 50%
- Border `transparent`
- Label "Manual"
- Does NOT pulse (it's passive, not alarming)

### Pulsing animation (non-operational)

Non-operational, non-unmonitored tiles get `animate-pulse`. Disabled when `prefers-reduced-motion: reduce`.

## Typography

```css
font-family: "IBM Plex Sans", ui-sans-serif, sans-serif;
font-variant-numeric: tabular-nums;   /* site-wide — steadies timestamps + counts */
```

Monospace is used for timestamps, IDs, counts, keyboard shortcut chips via:

```css
.font-mono, code, kbd, pre, samp, [data-tabular="true"] {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
}
```

**Current text sizes (Tailwind scale):**
- Page title (`h1`): `text-xl` (1.25rem) semibold
- Section headings: `text-[11px]` uppercase, tracking-wider, text-text-secondary
- Tile service name: `text-[13px]` medium
- Tile status label: `text-[11px]`
- Stale chip: `text-xs` (0.75rem)
- Body prose: `text-[13px]` for dense sections, `text-sm` (0.875rem) for readable sections

Spacing for the redesign: line length cap `max-w-prose` (65–75ch) on any reading-width content (brief descriptions, detail-panel narratives).

## Spacing / layout

- Base grid: 8px (Tailwind default is 4px — we use multiples of 2 = 8px effective)
- Page container: `max-w-5xl mx-auto px-4 sm:px-8 py-6 sm:py-8 space-y-5`
- Tile grid gap: `gap-2` (8px)
- Service grid columns: `grid-cols-2 sm:grid-cols-3 lg:grid-cols-4`
- Category block spacing: `space-y-5` between, `mb-2` between heading + grid
- Tile padding: `px-3.5 py-3` (~14px × 12px)
- Tile border-left accent: `3px` solid status color (or dashed for poller-broken)

## Motion

- Tile hover scale: `scale-[1.02]` — very subtle
- Tint transition: `duration-150`
- Drawer slide-in: `200ms ease-out` via custom `@keyframes slide-in` / `.animate-slide-in`
- Pulse: Tailwind default `animate-pulse`
- **All motion** disabled under `prefers-reduced-motion: reduce`

## Focus rings

```css
:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
  border-radius: 4px;
}
```

Every interactive element must preserve a visible focus ring. `outline-none` is forbidden without a replacement.

## Icons (Lucide)

All icons come from `lucide-react`. Current set used:
- `Activity` — flapping
- `CheckCircle2`, `AlertTriangle`, `AlertOctagon`, `XOctagon`, `HelpCircle` — status
- `WifiOff` — poller broken
- `Network` — dependency graph button

Icon sizing: 12–14px in tiles, 14–16px in header buttons. Stroke width `2.5` for denser rendering.

## Live announcements (a11y)

A single `role="status" aria-live="polite"` region near the page top announces only **headline** state changes (e.g., "2 active incidents: overall status degraded" or "All systems operational"). Per-tile changes do NOT announce — avoids spam.

## Keyboard shortcuts

- `j` / `↓` / `→` — next tile in grid
- `k` / `↑` / `←` — previous tile
- `Home` / `End` — jump to first / last
- `Enter` — open selected tile's detail drawer
- `g` — toggle dependency graph overlay (Engineer only)
- `?` — toggle keyboard-shortcuts overlay
- `Esc` — close open drawer / overlay

Input/textarea focus suppresses shortcuts.

## What Claude Design is free to change

- All hex values (so long as semantic ordering + contrast hold)
- Typography family + scale
- Spacing scale (within 8px grid)
- Radii, shadows, border weights
- Animation easings + durations (respecting reduced-motion)
- Icon set (if the new set still covers status semantics + poller-broken)
- Hover / focus micro-interactions

## What Claude Design must NOT change

- The five-state status taxonomy + severity rank
- Poller-broken distinct treatment (dashed or equivalent)
- Flapping badge surface (top-right of tile)
- Worst-first sort order
- Keyboard shortcut map
- Live-region announcement model
- Tailwind 4 `@theme` architecture (tokens as CSS vars)
- Self-hosted font requirement (no CDN fonts)
