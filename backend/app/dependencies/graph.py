"""Service dependency graph queries.

Provides functions to query upstream and downstream dependencies
from the service_dependencies table, enriched with current status.
"""

import aiosqlite

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


async def get_downstream(db: aiosqlite.Connection, service_id: str) -> list[dict]:
    """Get all services that are impacted when the given service breaks.

    Returns list of dicts with: service_id, service_name, impact_description,
    severity, current_status. Ordered by severity (critical first), then name.
    """
    cursor = await db.execute(
        """SELECT sd.downstream_service_id as service_id,
                  s.display_name as service_name,
                  sd.impact_description,
                  sd.severity,
                  s.current_status
           FROM service_dependencies sd
           JOIN services s ON s.id = sd.downstream_service_id
           WHERE sd.upstream_service_id = ?
           ORDER BY
               CASE sd.severity
                   WHEN 'critical' THEN 0
                   WHEN 'high' THEN 1
                   WHEN 'medium' THEN 2
                   WHEN 'low' THEN 3
               END,
               s.display_name""",
        (service_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_upstream(db: aiosqlite.Connection, service_id: str) -> list[dict]:
    """Get all services that the given service depends on.

    Returns list of dicts with: service_id, service_name, impact_description,
    severity, current_status. Ordered by severity (critical first), then name.
    """
    cursor = await db.execute(
        """SELECT sd.upstream_service_id as service_id,
                  s.display_name as service_name,
                  sd.impact_description,
                  sd.severity,
                  s.current_status
           FROM service_dependencies sd
           JOIN services s ON s.id = sd.upstream_service_id
           WHERE sd.downstream_service_id = ?
           ORDER BY
               CASE sd.severity
                   WHEN 'critical' THEN 0
                   WHEN 'high' THEN 1
                   WHEN 'medium' THEN 2
                   WHEN 'low' THEN 3
               END,
               s.display_name""",
        (service_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]
