"""Tests for the YAML config loader and database seeder."""

import pytest

from app.seed import (
    DependencyTarget,
    ServiceConfig,
    load_dependencies,
    load_services,
)


class TestServiceConfig:
    def test_valid_manual_service(self):
        svc = ServiceConfig(
            id="okta",
            display_name="Okta",
            category="identity",
            poll_type="manual",
        )
        assert svc.id == "okta"
        assert svc.poll_url is None

    def test_valid_polled_service(self):
        svc = ServiceConfig(
            id="box",
            display_name="Box",
            category="productivity",
            poll_type="statuspage_json",
            poll_url="https://status.box.com/api/v2/summary.json",
        )
        assert svc.poll_url == "https://status.box.com/api/v2/summary.json"

    def test_polled_service_without_url_fails(self):
        with pytest.raises(ValueError, match="requires a poll_url"):
            ServiceConfig(
                id="broken",
                display_name="Broken",
                category="other",
                poll_type="statuspage_json",
            )

    def test_invalid_category_fails(self):
        with pytest.raises(Exception):
            ServiceConfig(
                id="bad",
                display_name="Bad",
                category="invalid_category",
                poll_type="manual",
            )

    def test_invalid_poll_type_fails(self):
        with pytest.raises(Exception):
            ServiceConfig(
                id="bad",
                display_name="Bad",
                category="other",
                poll_type="invalid_type",
            )


class TestLoadServices:
    def test_loads_all_services(self):
        services = load_services()
        assert len(services) >= 25

    def test_service_types(self):
        services = load_services()
        poll_types = {s.poll_type for s in services}
        assert "statuspage_json" in poll_types
        assert "manual" in poll_types
        assert "google_json" in poll_types
        assert "slack_api" in poll_types

    def test_okta_is_manual(self):
        services = load_services()
        okta = next(s for s in services if s.id == "okta")
        assert okta.poll_type == "manual"

    def test_box_has_poll_url(self):
        services = load_services()
        box = next(s for s in services if s.id == "box")
        assert box.poll_type == "statuspage_json"
        assert "status.box.com" in str(box.poll_url)


class TestLoadDependencies:
    def test_loads_dependencies(self):
        deps = load_dependencies()
        assert "okta" in deps
        assert len(deps["okta"]) >= 10

    def test_okta_downstream_services(self):
        deps = load_dependencies()
        okta_targets = {t.service for t in deps["okta"]}
        assert "box" in okta_targets
        assert "slack" in okta_targets

    def test_okta_downstream_count(self):
        deps = load_dependencies()
        assert len(deps["okta"]) >= 10

    def test_cross_validation_accepts_matching_services(self):
        services = load_services()
        ids = {s.id for s in services}
        # Should not raise
        deps = load_dependencies(known_service_ids=ids)
        assert "okta" in deps

    def test_cross_validation_rejects_unknown_upstream(self, tmp_path):
        import yaml
        bad = tmp_path / "bad_deps.yaml"
        bad.write_text(yaml.safe_dump({
            "dependencies": {
                "ghost_service": [
                    {"service": "box", "impact": "x", "severity": "high"},
                ],
            },
        }))
        with pytest.raises(ValueError, match="Unknown upstream service 'ghost_service'"):
            load_dependencies(path=bad, known_service_ids={"box"})

    def test_cross_validation_rejects_unknown_downstream(self, tmp_path):
        import yaml
        bad = tmp_path / "bad_deps.yaml"
        bad.write_text(yaml.safe_dump({
            "dependencies": {
                "okta": [
                    {"service": "phantom_app", "impact": "x", "severity": "high"},
                ],
            },
        }))
        with pytest.raises(ValueError, match="Unknown downstream service 'phantom_app'"):
            load_dependencies(path=bad, known_service_ids={"okta"})

    def test_cross_validation_allows_all_internal_sentinel(self, tmp_path):
        import yaml
        good = tmp_path / "deps.yaml"
        good.write_text(yaml.safe_dump({
            "dependencies": {
                "okta": [
                    {"service": "all_internal", "impact": "x", "severity": "high"},
                ],
            },
        }))
        # Should not raise even though "all_internal" isn't in the id set
        deps = load_dependencies(path=good, known_service_ids={"okta"})
        assert deps["okta"][0].service == "all_internal"


class TestSeedDatabase:
    async def test_seed_services(self, db):
        services = load_services()
        count = await seed_services_with_db(db, services)
        assert count == len(services)

        cursor = await db.execute("SELECT count(*) FROM services")
        row = await cursor.fetchone()
        assert row[0] == len(services)

    async def test_seed_services_idempotent(self, db):
        services = load_services()
        await seed_services_with_db(db, services)
        await seed_services_with_db(db, services)

        cursor = await db.execute("SELECT count(*) FROM services")
        row = await cursor.fetchone()
        assert row[0] == len(services)  # Same count, not doubled

    async def test_seed_dependencies(self, db):
        services = load_services()
        await seed_services_with_db(db, services)

        deps = load_dependencies()
        all_ids = [s.id for s in services]
        count = await seed_deps_with_db(db, deps, all_ids)
        assert count >= 14

        cursor = await db.execute("SELECT count(*) FROM service_dependencies")
        row = await cursor.fetchone()
        assert row[0] >= 14

    async def test_okta_deps_seeded(self, db):
        services = load_services()
        await seed_services_with_db(db, services)

        deps = load_dependencies()
        all_ids = [s.id for s in services]
        await seed_deps_with_db(db, deps, all_ids)

        cursor = await db.execute(
            "SELECT count(*) FROM service_dependencies WHERE upstream_service_id='okta'"
        )
        row = await cursor.fetchone()
        assert row[0] == 12


# Helper functions that operate on a given db connection instead of the global one
async def seed_services_with_db(db, services: list[ServiceConfig]) -> int:
    for svc in services:
        await db.execute(
            """INSERT OR REPLACE INTO services
               (id, display_name, category, poll_type, poll_url,
                statuspage_component_name, status_page_url, current_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'unknown')""",
            (
                svc.id, svc.display_name, svc.category, svc.poll_type,
                svc.poll_url, svc.statuspage_component_name, svc.status_page_url,
            ),
        )
    await db.commit()
    return len(services)


async def seed_deps_with_db(
    db, deps: dict[str, list[DependencyTarget]], all_ids: list[str]
) -> int:
    await db.execute("DELETE FROM service_dependencies")
    count = 0
    for upstream, targets in deps.items():
        for target in targets:
            if target.service == "all_internal":
                downstream_ids = [sid for sid in all_ids if sid != upstream]
            else:
                downstream_ids = [target.service]
            for did in downstream_ids:
                await db.execute(
                    """INSERT OR IGNORE INTO service_dependencies
                       (upstream_service_id, downstream_service_id, impact_description, severity)
                       VALUES (?, ?, ?, ?)""",
                    (upstream, did, target.impact, target.severity),
                )
                count += 1
    await db.commit()
    return count
