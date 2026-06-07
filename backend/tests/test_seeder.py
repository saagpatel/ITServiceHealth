"""Tests for the YAML config loader and database seeder.

These tests load the committed example config explicitly (not the
settings-resolved path) so they stay deterministic even when an operator
has a gitignored services.local.yaml / dependencies.local.yaml present.
"""

from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.seed import (
    DependencyTarget,
    ServiceConfig,
    load_dependencies,
    load_services,
)

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_SERVICES_YAML = _CONFIG_DIR / "services.yaml"
_DEPENDENCIES_YAML = _CONFIG_DIR / "dependencies.yaml"


class TestServiceConfig:
    def test_valid_manual_service(self):
        svc = ServiceConfig(
            id="identity-provider",
            display_name="Identity Provider (SSO)",
            category="identity",
            poll_type="manual",
        )
        assert svc.id == "identity-provider"
        assert svc.poll_url is None

    def test_valid_polled_service(self):
        svc = ServiceConfig(
            id="github",
            display_name="GitHub",
            category="engineering",
            poll_type="statuspage_json",
            poll_url="https://www.githubstatus.com/api/v2/summary.json",
        )
        assert svc.poll_url == "https://www.githubstatus.com/api/v2/summary.json"

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
        services = load_services(path=_SERVICES_YAML)
        assert len(services) == 10

    def test_service_types(self):
        services = load_services(path=_SERVICES_YAML)
        poll_types = {s.poll_type for s in services}
        assert "statuspage_json" in poll_types
        assert "manual" in poll_types

    def test_identity_provider_is_manual(self):
        services = load_services(path=_SERVICES_YAML)
        idp = next(s for s in services if s.id == "identity-provider")
        assert idp.poll_type == "manual"

    def test_github_has_poll_url(self):
        services = load_services(path=_SERVICES_YAML)
        gh = next(s for s in services if s.id == "github")
        assert gh.poll_type == "statuspage_json"
        assert urlsplit(str(gh.poll_url)).hostname == "www.githubstatus.com"


class TestLoadDependencies:
    def test_loads_dependencies(self):
        deps = load_dependencies(path=_DEPENDENCIES_YAML)
        assert "identity-provider" in deps
        assert len(deps["identity-provider"]) == 8

    def test_sso_downstream_services(self):
        deps = load_dependencies(path=_DEPENDENCIES_YAML)
        targets = {t.service for t in deps["identity-provider"]}
        assert "github" in targets
        assert "dropbox" in targets

    def test_sso_downstream_count(self):
        deps = load_dependencies(path=_DEPENDENCIES_YAML)
        assert len(deps["identity-provider"]) == 8

    def test_cross_validation_accepts_matching_services(self):
        services = load_services(path=_SERVICES_YAML)
        ids = {s.id for s in services}
        # Should not raise — every edge references a known service id.
        deps = load_dependencies(path=_DEPENDENCIES_YAML, known_service_ids=ids)
        assert "identity-provider" in deps

    def test_cross_validation_rejects_unknown_upstream(self, tmp_path):
        import yaml

        bad = tmp_path / "bad_deps.yaml"
        bad.write_text(
            yaml.safe_dump(
                {
                    "dependencies": {
                        "ghost_service": [
                            {"service": "github", "impact": "x", "severity": "high"},
                        ],
                    },
                }
            )
        )
        with pytest.raises(ValueError, match="Unknown upstream service 'ghost_service'"):
            load_dependencies(path=bad, known_service_ids={"github"})

    def test_cross_validation_rejects_unknown_downstream(self, tmp_path):
        import yaml

        bad = tmp_path / "bad_deps.yaml"
        bad.write_text(
            yaml.safe_dump(
                {
                    "dependencies": {
                        "identity-provider": [
                            {"service": "phantom_app", "impact": "x", "severity": "high"},
                        ],
                    },
                }
            )
        )
        with pytest.raises(ValueError, match="Unknown downstream service 'phantom_app'"):
            load_dependencies(path=bad, known_service_ids={"identity-provider"})

    def test_cross_validation_allows_all_internal_sentinel(self, tmp_path):
        import yaml

        good = tmp_path / "deps.yaml"
        good.write_text(
            yaml.safe_dump(
                {
                    "dependencies": {
                        "identity-provider": [
                            {"service": "all_internal", "impact": "x", "severity": "high"},
                        ],
                    },
                }
            )
        )
        # Should not raise even though "all_internal" isn't in the id set
        deps = load_dependencies(path=good, known_service_ids={"identity-provider"})
        assert deps["identity-provider"][0].service == "all_internal"


class TestSeedDatabase:
    async def test_seed_services(self, db):
        services = load_services(path=_SERVICES_YAML)
        count = await seed_services_with_db(db, services)
        assert count == len(services)

        cursor = await db.execute("SELECT count(*) FROM services")
        row = await cursor.fetchone()
        assert row[0] == len(services)

    async def test_seed_services_idempotent(self, db):
        services = load_services(path=_SERVICES_YAML)
        await seed_services_with_db(db, services)
        await seed_services_with_db(db, services)

        cursor = await db.execute("SELECT count(*) FROM services")
        row = await cursor.fetchone()
        assert row[0] == len(services)  # Same count, not doubled

    async def test_seed_dependencies(self, db):
        services = load_services(path=_SERVICES_YAML)
        await seed_services_with_db(db, services)

        deps = load_dependencies(path=_DEPENDENCIES_YAML)
        all_ids = [s.id for s in services]
        count = await seed_deps_with_db(db, deps, all_ids)
        assert count == 10  # identity-provider (8 edges) + cloudflare (2 edges)

        cursor = await db.execute("SELECT count(*) FROM service_dependencies")
        row = await cursor.fetchone()
        assert row[0] == 10

    async def test_sso_deps_seeded(self, db):
        services = load_services(path=_SERVICES_YAML)
        await seed_services_with_db(db, services)

        deps = load_dependencies(path=_DEPENDENCIES_YAML)
        all_ids = [s.id for s in services]
        await seed_deps_with_db(db, deps, all_ids)

        cursor = await db.execute(
            "SELECT count(*) FROM service_dependencies "
            "WHERE upstream_service_id='identity-provider'"
        )
        row = await cursor.fetchone()
        assert row[0] == 8


# Helper functions that operate on a given db connection instead of the global one
async def seed_services_with_db(db, services: list[ServiceConfig]) -> int:
    for svc in services:
        await db.execute(
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
    await db.commit()
    return len(services)


async def seed_deps_with_db(db, deps: dict[str, list[DependencyTarget]], all_ids: list[str]) -> int:
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
