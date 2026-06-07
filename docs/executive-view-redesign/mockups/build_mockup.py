"""Render a high-fidelity mockup of the redesigned Executive view.

Matches the spec in docs/executive-view-redesign/IMPLEMENTATION-ROADMAP.md:
  - full-width status panel (112 px display headline)
  - 3 KPI tiles (incidents open / vendors degraded / SLA vs target)
  - 30-day trend strip
  - sorted impact list
  - dark theme, single alarm-red accent reserved for degraded/major states
  - 2x typography jumps: 14 / 28 / 56 / 112 px

Output:
  docs/executive-view-redesign/mockups/exec-operational.png (all systems operational)
  docs/executive-view-redesign/mockups/exec-major.png       (active incident view)
"""

from __future__ import annotations
import random

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, Rectangle

# --- tokens ---------------------------------------------------------------
BG_PAGE = "#0b1120"
SURFACE_1 = "#0f172a"
SURFACE_2 = "#1b2436"
BORDER = "#2a3446"
TEXT_DISPLAY = "#f8fafc"
TEXT_PRIMARY = "#f1f5f9"
TEXT_SECONDARY = "#94a3b8"
TEXT_DIM = "#64748b"
ACCENT_ALARM = "#ef4444"
OK_GREEN = "#34d399"
AREA_FILL = "#1b2436"

FONT = ["IBM Plex Sans", "Helvetica Neue", "Arial", "sans-serif"]
MONO = ["IBM Plex Mono", "Menlo", "Courier New", "monospace"]

# 1920 x 1080 aspect → fig size 16 x 9 inches at dpi 120 = 1920x1080
FIG_W, FIG_H = 16, 9


def build(variant: str, out: str) -> None:
    is_incident = variant == "major"

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    fig.patch.set_facecolor(BG_PAGE)
    ax.set_facecolor(BG_PAGE)
    ax.set_xlim(0, 160)
    ax.set_ylim(0, 90)
    ax.set_axis_off()

    def text(
        x,
        y,
        s,
        *,
        size,
        color=TEXT_PRIMARY,
        weight="normal",
        ha="left",
        va="center",
        family=FONT,
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

    # --- header strip ----------------------------------------------------
    text(6, 85.5, "Pulse", size=14, color=TEXT_DISPLAY, weight="bold")
    text(6, 82.5, "IT Service Health", size=9, color=TEXT_DIM)
    text(154, 85.5, "Executive", size=10, color=TEXT_SECONDARY, ha="right")
    text(
        154,
        82.5,
        "Last polled 12 s ago",
        size=8,
        color=TEXT_DIM,
        ha="right",
        family=MONO,
    )

    # --- primary status panel -------------------------------------------
    panel_y, panel_h = 64, 15
    panel_bg = ACCENT_ALARM if is_incident else SURFACE_1
    panel_fg = "#ffffff" if is_incident else TEXT_DISPLAY
    panel_sub = "#fecaca" if is_incident else TEXT_DIM
    panel_x, panel_w = 6, 148

    ax.add_patch(
        FancyBboxPatch(
            (panel_x, panel_y),
            panel_w,
            panel_h,
            boxstyle="round,pad=0.3,rounding_size=1.5",
            linewidth=0,
            facecolor=panel_bg,
        )
    )
    # status dot (small — single alarm-red reserved for panel fill, so dot is neutral white on red / green on dark)
    dot_color = "#ffffff" if is_incident else OK_GREEN
    ax.add_patch(plt.Circle((panel_x + 4, panel_y + panel_h / 2), 1.1, color=dot_color))

    headline = "2 Active Incidents" if is_incident else "All Systems Operational"
    subhead = (
        (
            "Identity provider (SSO) · major outage for 24 m   ·   "
            "Video conferencing · degraded for 11 m"
        )
        if is_incident
        else ("30 services monitored · 2 manual")
    )
    text(
        panel_x + 8,
        panel_y + panel_h * 0.60,
        headline,
        size=56,
        color=panel_fg,
        weight="bold",
    )
    text(panel_x + 8, panel_y + panel_h * 0.20, subhead, size=14, color=panel_sub)

    # --- three KPI tiles --------------------------------------------------
    tile_y, tile_h = 46, 14
    gap = 2
    tile_w = (panel_w - 2 * gap) / 3

    def kpi(i, label, value, delta=None, delta_neg=False):
        tx = panel_x + i * (tile_w + gap)
        ax.add_patch(
            FancyBboxPatch(
                (tx, tile_y),
                tile_w,
                tile_h,
                boxstyle="round,pad=0.3,rounding_size=1.5",
                linewidth=1,
                edgecolor=BORDER,
                facecolor=SURFACE_1,
            )
        )
        text(tx + 2, tile_y + tile_h - 2.3, label, size=11, color=TEXT_DIM)
        text(tx + 2, tile_y + 4.8, value, size=48, color=TEXT_DISPLAY, weight="bold")
        if delta:
            dc = ACCENT_ALARM if delta_neg else TEXT_DIM
            text(tx + 2, tile_y + 1.6, delta, size=11, color=dc, family=MONO)

    if is_incident:
        kpi(0, "Incidents open", "2")
        kpi(1, "Vendors degraded", "3")
        kpi(
            2,
            "SLA 30 d vs 99.90%",
            "99.42%",
            delta="−48 bps under target",
            delta_neg=True,
        )
    else:
        kpi(0, "Incidents open", "0")
        kpi(1, "Vendors degraded", "0")
        kpi(
            2,
            "SLA 30 d vs 99.90%",
            "99.97%",
            delta="+7 bps above target",
            delta_neg=False,
        )

    # --- 30-day trend strip ----------------------------------------------
    strip_y, strip_h = 29, 12
    ax.add_patch(
        FancyBboxPatch(
            (panel_x, strip_y),
            panel_w,
            strip_h,
            boxstyle="round,pad=0.3,rounding_size=1.5",
            linewidth=1,
            edgecolor=BORDER,
            facecolor=SURFACE_1,
        )
    )
    text(panel_x + 2, strip_y + strip_h - 1.8, "30-day uptime", size=11, color=TEXT_DIM)
    text(
        panel_x + panel_w - 2,
        strip_y + strip_h - 1.8,
        "99.42 – 100.00 %",
        size=10,
        color=TEXT_DIM,
        ha="right",
        family=MONO,
    )

    # synthetic but plausible series
    random.seed(7 if is_incident else 1)
    days = 30
    xs = np.linspace(panel_x + 3, panel_x + panel_w - 3, days)
    base = 99.95
    series = []
    for i in range(days):
        dip = 0.0
        if is_incident and i in (9, 22):
            dip = random.uniform(0.25, 0.55)
        elif is_incident and i == 28:
            dip = random.uniform(0.35, 0.58)
        else:
            dip = random.uniform(0.0, 0.05)
        series.append(base - dip + random.uniform(-0.01, 0.01))

    # scale to y pixels within strip interior (leave room for axis labels)
    y_top = strip_y + strip_h - 3.4
    y_bot = strip_y + 1.8
    lo, hi = min(series), 100.0
    rng = max(hi - lo, 0.05)
    ys = [y_bot + (v - lo) / rng * (y_top - y_bot) for v in series]

    # filled area
    verts = list(zip(xs, ys)) + [(xs[-1], y_bot), (xs[0], y_bot)]
    ax.add_patch(plt.Polygon(verts, closed=True, facecolor=AREA_FILL, edgecolor="none"))
    ax.plot(xs, ys, color=TEXT_SECONDARY, linewidth=1.3)

    # mark degraded days with alarm markers
    if is_incident:
        for idx in (9, 22, 28):
            ax.plot(
                [xs[idx]],
                [ys[idx]],
                marker="o",
                markerfacecolor=ACCENT_ALARM,
                markeredgecolor=ACCENT_ALARM,
                markersize=5,
            )

    # --- sorted impact list ----------------------------------------------
    list_y_top = 24
    list_y_bot = 5
    ax.add_patch(
        FancyBboxPatch(
            (panel_x, list_y_bot),
            panel_w,
            list_y_top - list_y_bot,
            boxstyle="round,pad=0.3,rounding_size=1.5",
            linewidth=1,
            edgecolor=BORDER,
            facecolor=SURFACE_1,
        )
    )
    text(panel_x + 2, list_y_top - 1.6, "Active impact", size=11, color=TEXT_DIM)
    text(
        panel_x + panel_w - 2,
        list_y_top - 1.6,
        f"{2 if is_incident else 0} / 30 affected",
        size=10,
        color=TEXT_DIM,
        ha="right",
        family=MONO,
    )

    if is_incident:
        rows = [
            (
                "Identity provider (SSO)",
                "Major outage",
                "SSO login completely unavailable — users cannot reach content, ticketing, and CRM tools",
                "24 m",
            ),
            (
                "Video conferencing",
                "Degraded",
                "Meeting start latency elevated · video dropouts reported by users",
                "11 m",
            ),
        ]
    else:
        rows = []

    row_h = 5.0
    for i, (name, status, line, since) in enumerate(rows):
        ry = list_y_top - 3.5 - (i + 1) * row_h
        # left accent bar
        ax.add_patch(
            Rectangle(
                (panel_x + 1.5, ry - 0.5),
                0.4,
                row_h - 0.6,
                facecolor=ACCENT_ALARM,
                edgecolor="none",
            )
        )
        text(
            panel_x + 3,
            ry + row_h * 0.55,
            name,
            size=22,
            color=TEXT_DISPLAY,
            weight="bold",
        )
        text(panel_x + 3, ry + row_h * 0.18, line, size=12, color=TEXT_SECONDARY)
        # status chip right side
        chip_x = panel_x + panel_w - 20
        ax.add_patch(
            FancyBboxPatch(
                (chip_x, ry + 1.5),
                10,
                2.2,
                boxstyle="round,pad=0.1,rounding_size=1.1",
                linewidth=0,
                facecolor=ACCENT_ALARM,
            )
        )
        text(
            chip_x + 5,
            ry + 2.6,
            status.upper(),
            size=9,
            color="#ffffff",
            weight="bold",
            ha="center",
            family=MONO,
        )
        # since
        text(
            panel_x + panel_w - 2,
            ry + row_h * 0.55,
            since,
            size=14,
            color=TEXT_SECONDARY,
            ha="right",
            family=MONO,
        )

    if not rows:
        text(
            panel_x + panel_w / 2,
            (list_y_top + list_y_bot) / 2,
            "No active impact",
            size=18,
            color=TEXT_DIM,
            ha="center",
            weight="normal",
        )

    # --- footer rule + caption -------------------------------------------
    ax.add_patch(
        Rectangle((panel_x, 3.0), panel_w, 0.08, facecolor=BORDER, edgecolor="none")
    )
    text(
        panel_x,
        1.6,
        "Pulse v2 · executive view · auto-refresh 30 s · internal read path",
        size=8,
        color=TEXT_DIM,
        family=MONO,
    )
    text(
        panel_x + panel_w,
        1.6,
        "docs/executive-view-redesign/mockups/" + out.split("/")[-1],
        size=8,
        color=TEXT_DIM,
        ha="right",
        family=MONO,
    )

    # --- save ------------------------------------------------------------
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(out, format="png", facecolor=BG_PAGE, dpi=120)
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    build("operational", "docs/executive-view-redesign/mockups/exec-operational.png")
    build("major", "docs/executive-view-redesign/mockups/exec-major.png")
