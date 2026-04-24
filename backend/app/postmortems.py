"""Generate Google-SRE-style Markdown postmortem drafts from incident reports.

Called by the alerting engine after generate_incident_report() returns a report
dict on service recovery. Two public entry points:

  render_markdown(report) -> str        — pure, no I/O
  write_postmortem(report, out_dir) -> Path | None  — atomic file write
"""

import contextlib
import hashlib
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_markdown(report: dict[str, Any]) -> str:
    """Render a Google-SRE-style postmortem Markdown string from an incident report.

    Args:
        report: Dict produced by generate_incident_report(). Must contain:
            service_id, service_name, started_at, resolved_at, duration_human,
            peak_severity, affected_downstream, event_count, impact_summary.
            Optionally contains an ``events`` list of status_event dicts.

    Returns:
        UTF-8 Markdown string with YAML frontmatter and 8 H2 sections.
    """
    parts: list[str] = []

    # -- YAML frontmatter ---------------------------------------------------
    frontmatter_data: dict[str, Any] = {
        "service": report["service_id"],
        "service_name": report["service_name"],
        "started_at": report["started_at"],
        "resolved_at": report["resolved_at"],
        "duration": report["duration_human"],
        "peak_severity": report["peak_severity"],
        "affected_downstream": report.get("affected_downstream", []),
        "event_count": report["event_count"],
        "status": "draft",
    }
    parts.append("---")
    parts.append(yaml.safe_dump(frontmatter_data, default_flow_style=False, sort_keys=False).rstrip())
    parts.append("---")
    parts.append("")

    # -- 1. Summary ---------------------------------------------------------
    parts.append("## Summary")
    parts.append("")
    parts.append(report.get("impact_summary", ""))
    parts.append("")

    # -- 2. Impact ----------------------------------------------------------
    parts.append("## Impact")
    parts.append("")
    parts.append(f"- **Peak severity:** {report['peak_severity']}")
    parts.append(f"- **Duration:** {report['duration_human']}")
    parts.append(f"- **Event count:** {report['event_count']}")
    affected: list[str] = report.get("affected_downstream", [])
    if affected:
        parts.append("- **Affected downstream services:**")
        for name in affected:
            parts.append(f"  - {name}")
    else:
        parts.append("- **Affected downstream services:** None")
    parts.append("")

    # -- 3. Root Cause -------------------------------------------------------
    parts.append("## Root Cause")
    parts.append("")
    parts.append("_TODO: Describe the root cause._")
    parts.append("")

    # -- 4. Timeline ---------------------------------------------------------
    parts.append("## Timeline")
    parts.append("")
    events: list[dict[str, Any]] = report.get("events", [])
    if events:
        for event in events:
            ts = _format_event_time(event.get("created_at", ""))
            prev = event.get("previous_status", "unknown")
            new = event.get("new_status", "unknown")
            detail = _pick_event_label(event)
            if detail:
                parts.append(f"- {ts} UTC — {prev} → {new}: {detail}")
            else:
                parts.append(f"- {ts} UTC — {prev} → {new}")
    else:
        parts.append("_No events recorded._")
    parts.append("")

    # -- 5. What Went Well ---------------------------------------------------
    parts.append("## What Went Well")
    parts.append("")
    parts.append("_TODO: What held up during this incident?_")
    parts.append("")

    # -- 6. What Went Poorly -------------------------------------------------
    parts.append("## What Went Poorly")
    parts.append("")
    parts.append("_TODO: Where did the response fall short?_")
    parts.append("")

    # -- 7. What Got Lucky ---------------------------------------------------
    parts.append("## What Got Lucky")
    parts.append("")
    parts.append("_TODO: What could have been worse but wasn't?_")
    parts.append("")

    # -- 8. Action Items -----------------------------------------------------
    parts.append("## Action Items")
    parts.append("")
    parts.append("### Prevent")
    parts.append("")
    parts.append("_TODO: How do we stop this class of incident from recurring?_")
    parts.append("")
    parts.append("### Mitigate")
    parts.append("")
    parts.append("_TODO: How do we reduce impact next time?_")
    parts.append("")
    parts.append("### Detect")
    parts.append("")
    parts.append("_TODO: How do we see it sooner?_")
    parts.append("")
    parts.append("### Repair")
    parts.append("")
    parts.append("_TODO: What follow-up repairs or backfills are needed?_")
    parts.append("")

    return "\n".join(parts)


async def write_postmortem(report: dict[str, Any], *, out_dir: Path) -> Path | None:
    """Write a postmortem draft for the given incident report.

    Returns the final Path on success, or None if the file already exists
    (idempotent — a re-run on the same incident is a no-op).

    Args:
        report: Dict produced by generate_incident_report().
        out_dir: Directory to write the postmortem Markdown file into.

    Raises:
        OSError: Propagated from failed atomic write so the caller can decide
                 whether to swallow or retry.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = _build_filename(report)
    final_path = out_dir / filename

    if final_path.exists():
        logger.debug("Postmortem already exists, skipping: %s", final_path)
        return None

    content = render_markdown(report)
    encoded = content.encode("utf-8")

    tmp_path = final_path.with_suffix(final_path.suffix + ".tmp")
    try:
        with tmp_path.open("wb") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, final_path)
    except OSError:
        logger.exception("Failed to write postmortem: %s", final_path)
        # Clean up orphaned .tmp if it exists
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise

    logger.info("Wrote postmortem: %s", final_path)
    return final_path


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_filename(report: dict[str, Any]) -> str:
    """Build the canonical postmortem filename.

    Format: {service_id}-{started_at_compact}-{6_char_sha}.md
    """
    service_id: str = report["service_id"]
    started_at: str = report["started_at"]
    resolved_at: str = report["resolved_at"]

    # Compact ISO timestamp: strip colons, drop microseconds, ensure trailing Z
    compact = _compact_timestamp(started_at)

    # Deterministic 6-char sha1 for idempotency — used only as a filename
    # collision tag, not a security primitive, so usedforsecurity=False.
    sha = hashlib.sha1(
        f"{started_at}|{resolved_at}".encode(), usedforsecurity=False,
    ).hexdigest()[:6]

    return f"{service_id}-{compact}-{sha}.md"


def _compact_timestamp(iso_ts: str) -> str:
    """Convert ISO 8601 timestamp to compact form: 20260424T141203Z."""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        dt_utc = dt.astimezone(UTC)
        return dt_utc.strftime("%Y%m%dT%H%M%SZ")
    except (ValueError, AttributeError):
        # Fall back to stripping colons from whatever string we have
        return iso_ts.replace(":", "").replace("-", "").replace(" ", "T").rstrip("Z") + "Z"


def _format_event_time(iso_ts: str) -> str:
    """Parse ISO 8601 timestamp and return HH:MM:SS string."""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone(UTC).strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return "??:??:??"


def _pick_event_label(event: dict[str, Any]) -> str:
    """Return the most descriptive label for a timeline entry.

    Preference: vendor_title > vendor_detail > impact_statement.
    Returns empty string if none are available.
    """
    for field in ("vendor_title", "vendor_detail", "impact_statement"):
        value = event.get(field)
        if value:
            return str(value)
    return ""
