"""Seed realistic historical incidents for demo purposes.

Creates 7 incidents over the past 7 days with realistic status progressions,
timestamps, and impact statements. Idempotent via 'demo-' vendor_incident_id prefix.

Usage: cd backend && python -m scripts.seed_demo_data
"""

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

# Adjust path so we can import from app/
sys.path.insert(0, ".")

from app.alerting.templates import generate_impact_statement
from app.database import close_db, get_db, get_write_lock, init_db
from app.dependencies.graph import get_downstream
from app.poller.change_detector import StatusChange

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

NOW = datetime.now(timezone.utc)


def days_ago(days, hour=10, minute=0):
    """Return a UTC datetime N days ago at the given hour (PT, converted to UTC)."""
    dt = NOW - timedelta(days=days)
    # PT is UTC-7; add 7 hours for UTC, handle day rollover
    utc_hour = hour + 7
    extra_days = utc_hour // 24
    utc_hour = utc_hour % 24
    dt = dt + timedelta(days=extra_days)
    return dt.replace(hour=utc_hour, minute=minute, second=0, microsecond=0)


# Each incident is a list of (service_id, display_name, prev_status, new_status, detail, timestamp, demo_id)
# Service ids match the committed example registry in config/services.yaml.
DEMO_INCIDENTS = [
    # 1. Identity provider degraded — 5 days ago, 4 hours
    [
        (
            "identity-provider",
            "Identity Provider (SSO)",
            "operational",
            "degraded",
            "Increased SSO login latency affecting some users",
            days_ago(5, 10, 0),
            "demo-1a",
        ),
        (
            "identity-provider",
            "Identity Provider (SSO)",
            "degraded",
            "operational",
            None,
            days_ago(5, 14, 0),
            "demo-1b",
        ),
    ],
    # 2. Discord partial outage — 4 days ago, 2 hours
    [
        (
            "discord",
            "Discord",
            "operational",
            "partial_outage",
            "Some users experiencing message delivery delays",
            days_ago(4, 14, 30),
            "demo-2a",
        ),
        (
            "discord",
            "Discord",
            "partial_outage",
            "degraded",
            "Issue identified, implementing fix",
            days_ago(4, 15, 15),
            "demo-2b",
        ),
        (
            "discord",
            "Discord",
            "degraded",
            "operational",
            None,
            days_ago(4, 16, 30),
            "demo-2c",
        ),
    ],
    # 3. Dropbox major outage — 6 days ago, 30 min
    [
        (
            "dropbox",
            "Dropbox",
            "operational",
            "major_outage",
            "File upload and download unavailable",
            days_ago(6, 11, 0),
            "demo-3a",
        ),
        (
            "dropbox",
            "Dropbox",
            "major_outage",
            "partial_outage",
            "Service partially restored, some operations slow",
            days_ago(6, 11, 15),
            "demo-3b",
        ),
        (
            "dropbox",
            "Dropbox",
            "partial_outage",
            "operational",
            None,
            days_ago(6, 11, 30),
            "demo-3c",
        ),
    ],
    # 4. Datadog degraded — 2 days ago, 1 hour
    [
        (
            "datadog",
            "Datadog",
            "operational",
            "degraded",
            "Delayed metric ingestion and dashboard updates",
            days_ago(2, 9, 0),
            "demo-4a",
        ),
        (
            "datadog",
            "Datadog",
            "degraded",
            "operational",
            None,
            days_ago(2, 10, 0),
            "demo-4b",
        ),
    ],
    # 5. Ticketing degraded — 1 day ago, 3 hours
    [
        (
            "ticketing",
            "Ticketing / ITSM",
            "operational",
            "degraded",
            "Slow page loads and search timeouts",
            days_ago(1, 15, 0),
            "demo-5a",
        ),
        (
            "ticketing",
            "Ticketing / ITSM",
            "degraded",
            "operational",
            None,
            days_ago(1, 18, 0),
            "demo-5b",
        ),
    ],
    # 6. GitHub degraded — 3 days ago, 1 hour
    [
        (
            "github",
            "GitHub",
            "operational",
            "degraded",
            "Elevated API error rates and delayed Actions runs",
            days_ago(3, 8, 0),
            "demo-6a",
        ),
        (
            "github",
            "GitHub",
            "degraded",
            "operational",
            None,
            days_ago(3, 9, 0),
            "demo-6b",
        ),
    ],
    # 7. Cloudflare + identity provider cascading — 4 days ago, 45 min
    [
        (
            "cloudflare",
            "Cloudflare",
            "operational",
            "degraded",
            "Elevated edge latency in some regions",
            days_ago(4, 16, 0),
            "demo-7a",
        ),
        (
            "identity-provider",
            "Identity Provider (SSO)",
            "operational",
            "degraded",
            "SSO logins slow due to upstream edge latency",
            days_ago(4, 16, 10),
            "demo-7b",
        ),
        (
            "identity-provider",
            "Identity Provider (SSO)",
            "degraded",
            "operational",
            None,
            days_ago(4, 16, 45),
            "demo-7c",
        ),
        (
            "cloudflare",
            "Cloudflare",
            "degraded",
            "operational",
            None,
            days_ago(4, 16, 45),
            "demo-7d",
        ),
    ],
]


async def seed_demo_data(db=None):
    """Seed all demo incidents into the database.

    Args:
        db: Optional existing DB connection. If None, initializes its own.
    """
    own_db = db is None
    if own_db:
        db = await init_db()

        # Ensure services are seeded (idempotent)
        from app.seed import (
            load_dependencies,
            load_services,
            seed_dependencies,
            seed_services,
        )

        services = load_services()
        await seed_services(services)
        deps = load_dependencies()
        await seed_dependencies(deps, [s.id for s in services])
        logger.info("Services and dependencies seeded")

    conn = db
    write_lock = get_write_lock()

    # Clear previous demo data (idempotent)
    async with write_lock:
        cursor = await conn.execute(
            "SELECT count(*) FROM status_events WHERE vendor_incident_id LIKE 'demo-%'"
        )
        existing = (await cursor.fetchone())[0]
        if existing > 0:
            await conn.execute(
                "DELETE FROM status_events WHERE vendor_incident_id LIKE 'demo-%'"
            )
            await conn.commit()
            logger.info("Cleared %d existing demo events", existing)

    total = 0
    for incident_group in DEMO_INCIDENTS:
        for (
            service_id,
            display_name,
            prev,
            new,
            detail,
            timestamp,
            demo_id,
        ) in incident_group:
            # Generate impact statement
            change = StatusChange(
                service_id=service_id,
                service_display_name=display_name,
                previous_status=prev,
                new_status=new,
                status_detail=detail,
                poll_type="demo",
                status_page_url=None,
            )
            downstream = await get_downstream(conn, service_id)
            impact = generate_impact_statement(change, downstream)

            ts = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

            async with write_lock:
                await conn.execute(
                    """INSERT INTO status_events
                       (service_id, previous_status, new_status, vendor_title,
                        vendor_detail, impact_statement, source, vendor_incident_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'demo', ?, ?)""",
                    (service_id, prev, new, detail, detail, impact, demo_id, ts),
                )
            total += 1

    async with write_lock:
        await conn.commit()

    logger.info(
        "Seeded %d demo events across %d incident scenarios", total, len(DEMO_INCIDENTS)
    )

    # Verify
    cursor = await conn.execute(
        "SELECT count(*) FROM status_events WHERE vendor_incident_id LIKE 'demo-%'"
    )
    count = (await cursor.fetchone())[0]
    logger.info("Total demo events in DB: %d", count)

    if own_db:
        await close_db()


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
