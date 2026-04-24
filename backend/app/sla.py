"""Reusable SLA uptime computation for a service over an arbitrary time window.

Used by router_services.py (/api/services/sla, /api/services/sla/history) and
the upcoming burn-rate alerting module.
"""

from dataclasses import dataclass
from datetime import datetime

import aiosqlite


@dataclass(frozen=True)
class WindowUptime:
    operational_seconds: float
    tracked_seconds: float
    uptime_percent: float | None  # None when tracked_seconds == 0


async def compute_uptime(
    db: aiosqlite.Connection,
    service_id: str,
    window_start: datetime,
    window_end: datetime,
) -> WindowUptime:
    """Compute operational uptime for *service_id* over [window_start, window_end).

    Behaviour mirrors the inline SQL that was previously inlined in the
    /api/services/sla endpoint:

    - Uses LEAD() to pair each status_events row with the timestamp of the next
      event, treating the open end as *window_end* (i.e. ``now`` for live calls).
    - Filters out ``previous_status='unknown' AND new_status='operational'``
      bootstrap transitions.
    - Intervals with ``status='unknown'`` are excluded from both
      ``tracked_seconds`` and ``operational_seconds``.
    - All intervals are clamped to [window_start, window_end] so that events
      that started before the window or end after the window contribute only
      their in-window portion.

    Args:
        db: An open aiosqlite connection (row_factory not required).
        service_id: The service to compute uptime for.
        window_start: Inclusive start of the window (timezone-aware recommended).
        window_end: Exclusive end of the window.

    Returns:
        A :class:`WindowUptime` instance.  ``uptime_percent`` is ``None`` when
        ``tracked_seconds`` is zero (no non-unknown data in the window).
    """
    # Fetch all events for this service that *could* overlap the window.
    # We need events that started before window_end (their interval may extend
    # into the window).  We also need one event before window_start to handle
    # the case where the service has been in the same status across the whole
    # window.  The simplest correct approach: fetch all events regardless of
    # start time and clamp in Python.
    cursor = await db.execute(
        """SELECT new_status AS status,
                  created_at AS started,
                  LEAD(created_at) OVER (ORDER BY created_at) AS ended
           FROM status_events
           WHERE service_id = ?
             AND NOT (previous_status = 'unknown' AND new_status = 'operational')
           ORDER BY created_at""",
        (service_id,),
    )
    rows = await cursor.fetchall()

    window_end_str = window_end.isoformat()

    operational_seconds = 0.0
    tracked_seconds = 0.0

    for row in rows:
        status = row[0]
        started_str = row[1]
        ended_str = row[2]

        if status == "unknown":
            continue

        try:
            start_dt = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
            end_dt = (
                datetime.fromisoformat(ended_str.replace("Z", "+00:00"))
                if ended_str
                else datetime.fromisoformat(window_end_str.replace("Z", "+00:00"))
            )
        except (ValueError, TypeError):
            continue

        # Clamp to [window_start, window_end]
        clamped_start = max(start_dt, window_start)
        clamped_end = min(end_dt, window_end)

        if clamped_start >= clamped_end:
            continue

        seconds = (clamped_end - clamped_start).total_seconds()
        tracked_seconds += seconds
        if status == "operational":
            operational_seconds += seconds

    uptime_percent: float | None
    if tracked_seconds > 0:
        raw = (operational_seconds / tracked_seconds) * 100
        uptime_percent = min(round(raw, 2), 100.0)
    else:
        uptime_percent = None

    return WindowUptime(
        operational_seconds=operational_seconds,
        tracked_seconds=tracked_seconds,
        uptime_percent=uptime_percent,
    )
