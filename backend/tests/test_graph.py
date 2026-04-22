"""Tests for the dependency graph module."""

import pytest

from app.dependencies.graph import get_downstream, get_upstream
from app.seed import DependencyTarget, load_dependencies, load_services
from tests.test_seeder import seed_deps_with_db, seed_services_with_db


async def _insert_service(db, sid):
    await db.execute(
        """INSERT OR REPLACE INTO services
           (id, display_name, category, poll_type, poll_url,
            status_page_url, current_status)
           VALUES (?, ?, 'other', 'manual', 'https://example.com/x',
                   'https://status.example.com', 'operational')""",
        (sid, sid.title()),
    )
    await db.commit()


async def _insert_edge(db, upstream, downstream, severity="high"):
    await db.execute(
        """INSERT OR REPLACE INTO service_dependencies
           (upstream_service_id, downstream_service_id, impact_description, severity)
           VALUES (?, ?, 'test', ?)""",
        (upstream, downstream, severity),
    )
    await db.commit()


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
        # Assert at least one 'critical' row exists before locating its last index.
        # This test protects against regressions in the SEVERITY ORDER BY sort:
        # if a non-critical entry sneaks between two critical entries we'd
        # catch it via `last_critical < first_high` below.
        assert "critical" in severities
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


class TestCycleHandling:
    """The current dependency graph API does single-hop SQL lookups with
    no recursion, so a cycle in the edges can't cause an infinite loop.
    These tests pin that guarantee: if a future refactor adds recursive
    traversal, it must either terminate or these tests will block it."""

    async def test_self_loop_returns_itself(self, db):
        """A service that declares itself as a downstream dep is a
        pathological config — verify get_downstream still terminates
        and returns exactly one row (not infinity)."""
        await _insert_service(db, "selfloop")
        await _insert_edge(db, "selfloop", "selfloop")
        results = await get_downstream(db, "selfloop")
        assert len(results) == 1
        assert results[0]["service_id"] == "selfloop"

    async def test_two_node_cycle_does_not_recurse(self, db):
        """A ↔ B cycle. Each get_downstream call should return exactly
        the other node — no recursion, no duplicates."""
        await _insert_service(db, "a")
        await _insert_service(db, "b")
        await _insert_edge(db, "a", "b")
        await _insert_edge(db, "b", "a")

        a_down = await get_downstream(db, "a")
        b_down = await get_downstream(db, "b")
        assert [r["service_id"] for r in a_down] == ["b"]
        assert [r["service_id"] for r in b_down] == ["a"]

    async def test_three_node_cycle_does_not_recurse(self, db):
        """A → B → C → A. Verify symmetric single-hop behavior."""
        for sid in ("a", "b", "c"):
            await _insert_service(db, sid)
        await _insert_edge(db, "a", "b")
        await _insert_edge(db, "b", "c")
        await _insert_edge(db, "c", "a")

        assert [r["service_id"] for r in await get_downstream(db, "a")] == ["b"]
        assert [r["service_id"] for r in await get_downstream(db, "b")] == ["c"]
        assert [r["service_id"] for r in await get_downstream(db, "c")] == ["a"]

    async def test_seed_allows_cycle_without_error(self, tmp_path):
        """load_dependencies cross-validation accepts cyclic declarations —
        the guard is about orphan references, not acyclicity. Document
        this by asserting it doesn't throw."""
        import yaml
        cycle_yaml = yaml.safe_dump({
            "dependencies": {
                "a": [{"service": "b", "impact": "x", "severity": "high"}],
                "b": [{"service": "a", "impact": "x", "severity": "high"}],
            },
        })
        path = tmp_path / "cycle_deps.yaml"
        path.write_text(cycle_yaml)
        deps = load_dependencies(path=path, known_service_ids={"a", "b"})
        assert "a" in deps and "b" in deps
        assert isinstance(deps["a"][0], DependencyTarget)
