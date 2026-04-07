"""Tests for the dependency graph module."""

import pytest

from app.dependencies.graph import get_downstream, get_upstream
from app.seed import load_dependencies, load_services
from tests.test_seeder import seed_deps_with_db, seed_services_with_db


@pytest.fixture
async def seeded_db(db):
    """DB with services and dependencies seeded."""
    services = load_services()
    await seed_services_with_db(db, services)
    deps = load_dependencies()
    await seed_deps_with_db(db, deps, [s.id for s in services])
    return db


class TestGetDownstream:
    async def test_okta_has_12_downstream(self, seeded_db):
        results = await get_downstream(seeded_db, "okta")
        assert len(results) == 12

    async def test_okta_downstream_includes_box(self, seeded_db):
        results = await get_downstream(seeded_db, "okta")
        ids = [r["service_id"] for r in results]
        assert "box" in ids
        assert "slack" in ids
        assert "zoom" in ids

    async def test_downstream_ordered_by_severity(self, seeded_db):
        results = await get_downstream(seeded_db, "okta")
        severities = [r["severity"] for r in results]
        first_critical = next(i for i, s in enumerate(severities) if s == "critical")
        last_critical = len(severities) - 1 - next(
            i for i, s in enumerate(reversed(severities)) if s == "critical"
        )
        first_high = next((i for i, s in enumerate(severities) if s == "high"), len(severities))
        assert last_critical < first_high or first_high == len(severities)

    async def test_downstream_includes_current_status(self, seeded_db):
        results = await get_downstream(seeded_db, "okta")
        for r in results:
            assert "current_status" in r
            assert r["current_status"] is not None

    async def test_no_downstream(self, seeded_db):
        results = await get_downstream(seeded_db, "coupa")
        assert results == []

    async def test_nonexistent_service(self, seeded_db):
        results = await get_downstream(seeded_db, "nonexistent")
        assert results == []


class TestGetUpstream:
    async def test_box_upstream_includes_okta(self, seeded_db):
        results = await get_upstream(seeded_db, "box")
        ids = [r["service_id"] for r in results]
        assert "okta" in ids

    async def test_okta_upstream_includes_duo(self, seeded_db):
        results = await get_upstream(seeded_db, "okta")
        ids = [r["service_id"] for r in results]
        assert "duo" in ids

    async def test_no_upstream(self, seeded_db):
        results = await get_upstream(seeded_db, "duo")
        assert results == []
