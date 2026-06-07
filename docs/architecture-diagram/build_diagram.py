"""Build the Pulse / IT Service Health architecture diagram as landscape-letter PDF.

Output: docs/architecture-diagram/architecture.pdf (11 x 8.5 in)

Visual system matches the Executive-view redesign:
  - dark background #0b1120
  - surface #151d2e, border #1e293b
  - primary text #f1f5f9, secondary #94a3b8, muted #64748b
  - single alarm-red accent #ef4444 reserved for resilience-gate callouts
"""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

# --- tokens ---------------------------------------------------------------
BG_PAGE = "#0b1120"
SURFACE = "#151d2e"
SURFACE_ELEV = "#1b2436"
BORDER = "#2a3446"
BORDER_STRONG = "#3a4557"
TEXT_PRIMARY = "#f1f5f9"
TEXT_SECONDARY = "#94a3b8"
TEXT_MUTED = "#64748b"
ACCENT_ALARM = "#ef4444"
ACCENT_DIM_RED = "#7f1d1d"

FONT_FAMILY = ["IBM Plex Sans", "Helvetica Neue", "Arial", "sans-serif"]
FONT_MONO = ["IBM Plex Mono", "Menlo", "Courier New", "monospace"]

# --- figure ---------------------------------------------------------------
fig, ax = plt.subplots(figsize=(11, 8.5))
fig.patch.set_facecolor(BG_PAGE)
ax.set_facecolor(BG_PAGE)
ax.set_xlim(0, 110)
ax.set_ylim(0, 85)
ax.set_axis_off()


def text(
    x,
    y,
    s,
    *,
    size=8,
    color=TEXT_PRIMARY,
    weight="normal",
    ha="left",
    va="center",
    family=FONT_FAMILY,
):
    ax.text(
        x,
        y,
        s,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        family=family,
    )


def node(
    x,
    y,
    w,
    h,
    title,
    subtitle=None,
    *,
    border=BORDER,
    fill=SURFACE,
    title_size=9,
    sub_size=7,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.2,rounding_size=1.2",
        linewidth=1.2,
        edgecolor=border,
        facecolor=fill,
    )
    ax.add_patch(patch)
    if subtitle:
        text(
            x + w / 2,
            y + h * 0.62,
            title,
            size=title_size,
            color=TEXT_PRIMARY,
            weight="bold",
            ha="center",
        )
        text(
            x + w / 2,
            y + h * 0.28,
            subtitle,
            size=sub_size,
            color=TEXT_SECONDARY,
            ha="center",
        )
    else:
        text(
            x + w / 2,
            y + h / 2,
            title,
            size=title_size,
            color=TEXT_PRIMARY,
            weight="bold",
            ha="center",
        )


def arrow(x1, y1, x2, y2, *, color=TEXT_MUTED, lw=1.3):
    arr = FancyArrowPatch(
        (x1, y1),
        (x2, y2),
        arrowstyle="-|>",
        mutation_scale=10,
        color=color,
        linewidth=lw,
        shrinkA=2,
        shrinkB=2,
    )
    ax.add_patch(arr)


# --- title banner ---------------------------------------------------------
text(5, 79.5, "Pulse — IT Service Health", size=18, color=TEXT_PRIMARY, weight="bold")
text(
    5,
    76.2,
    "Production architecture · vendor status pages → React dashboard · v2 shipped · 276 tests",
    size=9,
    color=TEXT_SECONDARY,
)
text(105, 79.5, "Enterprise IT · Internal", size=9, color=TEXT_MUTED, ha="right")
text(
    105,
    76.2,
    "Landscape · 11 × 8.5 in",
    size=8,
    color=TEXT_MUTED,
    ha="right",
    family=FONT_MONO,
)

# thin rule under title
ax.add_patch(Rectangle((5, 74), 100, 0.15, facecolor=BORDER_STRONG, edgecolor="none"))

# --- swim-lane backdrops --------------------------------------------------
# Resilience gates lane (top)
ax.add_patch(
    FancyBboxPatch(
        (5, 61.5),
        100,
        9,
        boxstyle="round,pad=0.2,rounding_size=1.2",
        linewidth=1.0,
        edgecolor=ACCENT_DIM_RED,
        facecolor="#1a0f12",
    )
)
text(6.5, 68.8, "Resilience gates", size=9, color=ACCENT_ALARM, weight="bold")
text(
    6.5,
    66.5,
    "stamina — exponential backoff with jitter on every vendor HTTP call",
    size=7.5,
    color=TEXT_SECONDARY,
)
text(
    6.5,
    64.6,
    "purgatory — per-host circuit breaker, 3 consecutive fails → open for 300 s, poller_health flips to broken",
    size=7.5,
    color=TEXT_SECONDARY,
)

# Observability lane (bottom)
ax.add_patch(
    FancyBboxPatch(
        (5, 6),
        100,
        9,
        boxstyle="round,pad=0.2,rounding_size=1.2",
        linewidth=1.0,
        edgecolor=BORDER_STRONG,
        facecolor=SURFACE_ELEV,
    )
)
text(6.5, 12.6, "Observability", size=9, color=TEXT_PRIMARY, weight="bold")

# observability chips — four services as inline pills
obs_y = 8.3
obs_x_start = 24
chip_defs = [
    ("structlog", "JSON logs, request + correlation ids"),
    ("Prometheus", "/metrics — poll latency, breaker state, SLA"),
    ("Sentry", "unhandled exceptions + release tagging"),
    ("Healthchecks.io", "dead-man's switch · 30 s heartbeat"),
]
chip_w = 19.5
chip_gap = 1.0
for i, (name, desc) in enumerate(chip_defs):
    cx = obs_x_start + i * (chip_w + chip_gap)
    ax.add_patch(
        FancyBboxPatch(
            (cx, obs_y),
            chip_w,
            4.0,
            boxstyle="round,pad=0.15,rounding_size=0.8",
            linewidth=1.0,
            edgecolor=BORDER_STRONG,
            facecolor=SURFACE,
        )
    )
    text(
        cx + chip_w / 2,
        obs_y + 2.7,
        name,
        size=8,
        color=TEXT_PRIMARY,
        weight="bold",
        ha="center",
    )
    text(cx + chip_w / 2, obs_y + 1.1, desc, size=6.5, color=TEXT_MUTED, ha="center")

# --- pipeline row ---------------------------------------------------------
# Two content rows inside the body:
#   row A (top of body): vendor sources + poll loop + normalization
#   row B (middle):      detection → impact → alert
#   row C (bottom of body): persistence → API → dashboard

# --- Column 1: vendor sources ---------------------------------------------
col1_x = 6
col1_w = 18
ax.add_patch(
    FancyBboxPatch(
        (col1_x, 34),
        col1_w,
        22,
        boxstyle="round,pad=0.2,rounding_size=1.2",
        linewidth=1.2,
        edgecolor=BORDER,
        facecolor=SURFACE,
    )
)
text(
    col1_x + col1_w / 2,
    53.8,
    "Vendor status sources",
    size=9,
    color=TEXT_PRIMARY,
    weight="bold",
    ha="center",
)
text(
    col1_x + col1_w / 2,
    51.8,
    "30 services · ~60 s cadence",
    size=7,
    color=TEXT_MUTED,
    ha="center",
    family=FONT_MONO,
)
vendor_lines = [
    ("Statuspage.io JSON", "15 services"),
    ("Chat vendor status API", "1 service"),
    ("Productivity suite feed", "2 services"),
    ("Manual POST /api/admin", "11 services"),
]
for i, (label, count) in enumerate(vendor_lines):
    ly = 49.0 - i * 3.1
    text(col1_x + 1.2, ly + 0.4, label, size=7.5, color=TEXT_SECONDARY)
    text(
        col1_x + col1_w - 1.2,
        ly + 0.4,
        count,
        size=7,
        color=TEXT_MUTED,
        ha="right",
        family=FONT_MONO,
    )

# --- Column 2: poll orchestrator + normalizer -----------------------------
col2_x = 28
col2_w = 18
node(
    col2_x,
    47.5,
    col2_w,
    8,
    "Poll Orchestrator",
    "APScheduler · async httpx · 60 s interval",
    border=ACCENT_DIM_RED,
)
node(
    col2_x,
    36,
    col2_w,
    8,
    "Status Normalizer",
    "5-state: operational · degraded · partial · major · unknown",
)

# --- Column 3: change detector + impact engine ----------------------------
col3_x = 50
col3_w = 18
node(
    col3_x,
    47.5,
    col3_w,
    8,
    "Change Detector",
    "diff vs current DB row · writes status_events",
)
node(
    col3_x,
    36,
    col3_w,
    8,
    "Impact Statement Engine",
    "dependency graph · templated impact copy",
)

# --- Column 4: alert quality layer + SQLite writer ------------------------
col4_x = 72
col4_w = 18
# taller node for alert quality because it carries sublayer annotations
ax.add_patch(
    FancyBboxPatch(
        (col4_x, 43),
        col4_w,
        12.5,
        boxstyle="round,pad=0.2,rounding_size=1.2",
        linewidth=1.4,
        edgecolor=ACCENT_ALARM,
        facecolor="#1a0f12",
    )
)
text(
    col4_x + col4_w / 2,
    53.3,
    "Alert Quality Layer",
    size=9,
    color=TEXT_PRIMARY,
    weight="bold",
    ha="center",
)
text(
    col4_x + col4_w / 2,
    51.5,
    "Slack Block Kit → the ops-alert channel",
    size=7,
    color=TEXT_SECONDARY,
    ha="center",
)
aq_lines = [
    "flap suppression · 3-poll confirm",
    "dedup window · vendor_incident_id",
    "tier routing · critical vs. informational",
    "dep. correlation · aggregate upstream",
    "maintenance windows · suppress planned",
]
for i, line in enumerate(aq_lines):
    text(col4_x + 1.2, 49.2 - i * 1.2, line, size=6.8, color=TEXT_SECONDARY)

node(col4_x, 33, col4_w, 7.5, "SQLite Writer", "WAL · aiosqlite pool · retention job")

# --- Column 5: API + React dashboard --------------------------------------
col5_x = 92
col5_w = 13
node(col5_x, 47.5, col5_w, 8, "FastAPI", "/api/services · /api/summary · /api/timeline")
node(col5_x, 36, col5_w, 8, "React Dashboard", "Exec · Engineer · PWA · recharts")

# --- Persistence annotations row ------------------------------------------
# Under SQLite Writer → explain Litestream + VACUUM INTO
dl_x, dl_w = col4_x - 2, 20  # ends at 90
ax.add_patch(
    FancyBboxPatch(
        (dl_x, 18.5),
        dl_w,
        11,
        boxstyle="round,pad=0.2,rounding_size=1.2",
        linewidth=1.0,
        edgecolor=BORDER,
        facecolor=SURFACE_ELEV,
    )
)
text(
    dl_x + dl_w / 2,
    27.5,
    "Data lifecycle",
    size=8.5,
    color=TEXT_PRIMARY,
    weight="bold",
    ha="center",
)
dl_lines = [
    "Litestream · WAL frames · ~1 s RPO",
    "daily VACUUM INTO · 7 d retention",
    "status_events · 90 d retention",
    "WAL checkpoint · 24 h cadence",
]
for i, line in enumerate(dl_lines):
    text(dl_x + 1.0, 25.2 - i * 1.4, line, size=6.8, color=TEXT_SECONDARY)

# --- Auth + deployment annotations (below API) ----------------------------
edge_x, edge_w = 91, 14  # starts at 91 so no overlap with dl_x+dl_w = 90
ax.add_patch(
    FancyBboxPatch(
        (edge_x, 18.5),
        edge_w,
        11,
        boxstyle="round,pad=0.2,rounding_size=1.2",
        linewidth=1.0,
        edgecolor=BORDER,
        facecolor=SURFACE_ELEV,
    )
)
text(
    edge_x + edge_w / 2,
    27.5,
    "Edge",
    size=8.5,
    color=TEXT_PRIMARY,
    weight="bold",
    ha="center",
)
edge_lines = [
    "Caddy · HTTPS + header auth",
    "internal-network-only read path",
    "Bearer-token write path",
    "launchd · Mac Mini 24/7",
]
for i, line in enumerate(edge_lines):
    text(edge_x + 1.0, 25.2 - i * 1.4, line, size=6.8, color=TEXT_SECONDARY)

# --- Pipeline arrows ------------------------------------------------------
# Row A (top of pipeline body): vendor sources → poll → normalizer
arrow(col1_x + col1_w, 51.5, col2_x, 51.5)
arrow(col2_x + col2_w / 2, 47.5, col2_x + col2_w / 2, 44.0)

# Normalizer → Change Detector
arrow(col2_x + col2_w, 40, col3_x, 47.5 + 4, color=TEXT_MUTED)

# Change Detector → Impact Engine
arrow(col3_x + col3_w / 2, 47.5, col3_x + col3_w / 2, 44.0)

# Impact Engine → Alert Quality
arrow(col3_x + col3_w, 40, col4_x, 49, color=ACCENT_ALARM)

# Impact Engine → SQLite Writer
arrow(col3_x + col3_w, 38, col4_x, 36.5, color=TEXT_MUTED)

# Alert Quality → Slack (inline right chevron + label)
text(
    col4_x + col4_w + 0.7,
    49,
    "→ Slack",
    size=7,
    color=ACCENT_ALARM,
    weight="bold",
    family=FONT_MONO,
)

# SQLite Writer → FastAPI (horizontal right)
arrow(col4_x + col4_w, 36.5, col5_x, 40)

# FastAPI → React Dashboard
arrow(col5_x + col5_w / 2, 47.5, col5_x + col5_w / 2, 44.0)

# Resilience gate tether: an alarm-red dashed tether from the resilience lane
# down onto the Poll Orchestrator node border
tether = FancyArrowPatch(
    (col2_x + col2_w / 2, 61.3),
    (col2_x + col2_w / 2, 55.5),
    arrowstyle="-",
    linestyle=(0, (2, 2)),
    color=ACCENT_ALARM,
    linewidth=1.2,
)
ax.add_patch(tether)
text(
    col2_x + col2_w / 2 + 0.5,
    58.5,
    "guards",
    size=7,
    color=ACCENT_ALARM,
    weight="bold",
    family=FONT_MONO,
)

# Observability tether: neutral dashed line spanning the full pipeline up
# to each processing stage
for cx in [
    col2_x + col2_w / 2,
    col3_x + col3_w / 2,
    col4_x + col4_w / 2,
    col5_x + col5_w / 2,
]:
    t = FancyArrowPatch(
        (cx, 15),
        (cx, 33),
        arrowstyle="-",
        linestyle=(0, (1, 2)),
        color=TEXT_MUTED,
        linewidth=0.8,
    )
    ax.add_patch(t)
text(
    18,
    15.8,
    "instruments every stage →",
    size=7,
    color=TEXT_MUTED,
    family=FONT_MONO,
    weight="bold",
)

# --- Footer ---------------------------------------------------------------
ax.add_patch(Rectangle((5, 3.5), 100, 0.1, facecolor=BORDER, edgecolor="none"))
text(
    5,
    2.0,
    "Python 3.12 · FastAPI 0.115 · httpx 0.28 · APScheduler 3.10 · SQLite + Litestream · React 19 + Vite 8 · Tailwind 4 · recharts 3",
    size=7,
    color=TEXT_MUTED,
    family=FONT_MONO,
)
text(
    105,
    2.0,
    "docs/architecture-diagram/architecture.pdf",
    size=7,
    color=TEXT_MUTED,
    ha="right",
    family=FONT_MONO,
)

# --- save -----------------------------------------------------------------
# Lock the exact landscape-letter page size — do NOT use bbox_inches="tight"
# because that would crop to the drawn content and yield a non-letter page.
fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
out = "docs/architecture-diagram/architecture.pdf"
fig.savefig(out, format="pdf", facecolor=BG_PAGE)
fig.savefig(
    "docs/architecture-diagram/architecture.png",
    format="png",
    facecolor=BG_PAGE,
    dpi=200,
)
print(f"wrote {out}")
