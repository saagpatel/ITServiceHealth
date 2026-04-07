"""YAML config loader with Pydantic validation and idempotent database seeder."""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from app.config import settings
from app.database import close_db, get_write_lock, init_db

logger = logging.getLogger(__name__)

VALID_CATEGORIES = Literal[
    "identity", "productivity", "collaboration", "engineering",
    "hr", "finance", "sales", "marketing", "networking", "support", "other",
]

VALID_POLL_TYPES = Literal[
    "statuspage_json", "google_json", "slack_api", "rss", "manual",
    "salesforce_trust", "zendesk_api", "ringcentral_api",
]


class ServiceConfig(BaseModel):
    """Pydantic model for validating a service entry in services.yaml."""

    id: str
    display_name: str
    category: VALID_CATEGORIES
    poll_type: VALID_POLL_TYPES
    poll_url: str | None = None
    statuspage_component_name: str | None = None
    status_page_url: str | None = None

    @model_validator(mode="after")
    def require_url_for_polled_services(self) -> "ServiceConfig":
        if self.poll_type != "manual" and not self.poll_url:
            raise ValueError(
                f"Service '{self.id}': poll_type='{self.poll_type}' requires a poll_url"
            )
        return self


class DependencyTarget(BaseModel):
    """A single downstream dependency edge."""

    service: str
    impact: str
    severity: Literal["critical", "high", "medium", "low"] = "high"


def load_services(path: Path | None = None) -> list[ServiceConfig]:
    """Load and validate services.yaml, returning typed ServiceConfig objects."""
    yaml_path = path or settings.services_yaml_path
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    raw_services = data.get("services", [])
    if not raw_services:
        raise ValueError(f"No services found in {yaml_path}")

    services = []
    errors = []
    for i, raw in enumerate(raw_services):
        try:
            services.append(ServiceConfig.model_validate(raw))
        except Exception as e:
            errors.append(f"  Service #{i + 1} ({raw.get('id', '?')}): {e}")

    if errors:
        raise ValueError(
            f"Validation failed for {len(errors)} service(s):\n" + "\n".join(errors)
        )

    return services


def load_dependencies(
    path: Path | None = None,
) -> dict[str, list[DependencyTarget]]:
    """Load and validate dependencies.yaml."""
    yaml_path = path or settings.dependencies_yaml_path
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    raw_deps = data.get("dependencies", {})
    deps: dict[str, list[DependencyTarget]] = {}

    for upstream, targets in raw_deps.items():
        deps[upstream] = [DependencyTarget.model_validate(t) for t in targets]

    return deps


async def seed_services(services: list[ServiceConfig]) -> int:
    """Upsert services into the database. Returns count of services seeded."""
    from app.database import get_db

    conn = await get_db()
    async with get_write_lock():
        for svc in services:
            await conn.execute(
                """INSERT OR REPLACE INTO services
                   (id, display_name, category, poll_type, poll_url,
                    statuspage_component_name, status_page_url, current_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'unknown')""",
                (
                    svc.id,
                    svc.display_name,
                    svc.category,
                    svc.poll_type,
                    svc.poll_url,
                    svc.statuspage_component_name,
                    svc.status_page_url,
                ),
            )
        await conn.commit()

    return len(services)


async def seed_dependencies(
    deps: dict[str, list[DependencyTarget]],
    all_service_ids: list[str],
) -> int:
    """Replace all dependencies in the database. Returns count of edges inserted."""
    from app.database import get_db

    conn = await get_db()
    count = 0

    async with get_write_lock():
        await conn.execute("DELETE FROM service_dependencies")

        for upstream, targets in deps.items():
            for target in targets:
                # Expand "all_internal" to all services except the upstream itself
                if target.service == "all_internal":
                    downstream_ids = [
                        sid for sid in all_service_ids if sid != upstream
                    ]
                else:
                    downstream_ids = [target.service]

                for downstream_id in downstream_ids:
                    await conn.execute(
                        """INSERT OR IGNORE INTO service_dependencies
                           (upstream_service_id, downstream_service_id,
                            impact_description, severity)
                           VALUES (?, ?, ?, ?)""",
                        (upstream, downstream_id, target.impact, target.severity),
                    )
                    count += 1

        await conn.commit()

    return count


async def seed_all(clean: bool = False) -> None:
    """Run the full seeding pipeline: load YAML, validate, insert into DB."""
    conn = await init_db()

    if clean:
        logger.warning("Clean mode: wiping all tables")
        async with get_write_lock():
            await conn.execute("DELETE FROM scheduled_maintenances")
            await conn.execute("DELETE FROM status_events")
            await conn.execute("DELETE FROM service_dependencies")
            await conn.execute("DELETE FROM services")
            await conn.commit()

    # Load and validate YAML configs
    logger.info("Loading services from %s", settings.services_yaml_path)
    services = load_services()
    logger.info("Validated %d services", len(services))

    logger.info("Loading dependencies from %s", settings.dependencies_yaml_path)
    deps = load_dependencies()
    logger.info("Loaded dependencies for %d upstream services", len(deps))

    # Seed database
    svc_count = await seed_services(services)
    logger.info("Seeded %d services", svc_count)

    all_ids = [s.id for s in services]
    dep_count = await seed_dependencies(deps, all_ids)
    logger.info("Seeded %d dependency edges", dep_count)

    # Summary
    cursor = await conn.execute("SELECT count(*) FROM services")
    row = await cursor.fetchone()
    logger.info("Total services in DB: %d", row[0])

    cursor = await conn.execute("SELECT count(*) FROM service_dependencies")
    row = await cursor.fetchone()
    logger.info("Total dependency edges in DB: %d", row[0])

    await close_db()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    clean = "--clean" in sys.argv
    asyncio.run(seed_all(clean=clean))
