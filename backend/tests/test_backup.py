"""Tests for the database backup module."""

import sqlite3
from datetime import date, timedelta
from unittest.mock import patch

import aiosqlite
import pytest

from app.backup import cleanup_old_backups, run_backup
from app.config import settings
from app.database import run_migrations


@pytest.fixture
async def file_db(tmp_path):
    """Provide a file-based database (VACUUM INTO requires a real file)."""
    db_path = tmp_path / "test.db"
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(conn, settings.migrations_dir)
    # Insert a test service directly
    await conn.execute(
        """INSERT INTO services (id, display_name, category, poll_type, current_status)
           VALUES ('test-svc', 'Test Service', 'productivity', 'manual', 'operational')"""
    )
    await conn.commit()
    yield conn
    await conn.close()


class TestRunBackup:
    @pytest.fixture
    def backup_dir(self, tmp_path):
        return tmp_path / "backups"

    @pytest.mark.asyncio
    async def test_creates_backup_file(self, backup_dir, file_db):
        with patch("app.backup.get_db", return_value=file_db), \
             patch("app.backup.settings") as mock_settings:
            mock_settings.backup_dir = str(backup_dir)
            mock_settings.backup_retention_days = 7
            await run_backup()

        backup_files = list(backup_dir.glob("pulse-*.db"))
        assert len(backup_files) == 1
        assert backup_files[0].name == f"pulse-{date.today().isoformat()}.db"

    @pytest.mark.asyncio
    async def test_backup_is_valid_sqlite(self, backup_dir, file_db):
        with patch("app.backup.get_db", return_value=file_db), \
             patch("app.backup.settings") as mock_settings:
            mock_settings.backup_dir = str(backup_dir)
            mock_settings.backup_retention_days = 7
            await run_backup()

        backup_path = backup_dir / f"pulse-{date.today().isoformat()}.db"
        conn = sqlite3.connect(str(backup_path))
        cursor = conn.execute("SELECT count(*) FROM services")
        count = cursor.fetchone()[0]
        conn.close()
        assert count > 0

    @pytest.mark.asyncio
    async def test_skips_if_already_exists(self, backup_dir, file_db):
        backup_dir.mkdir(parents=True)
        existing = backup_dir / f"pulse-{date.today().isoformat()}.db"
        existing.write_text("dummy")

        with patch("app.backup.get_db", return_value=file_db), \
             patch("app.backup.settings") as mock_settings:
            mock_settings.backup_dir = str(backup_dir)
            mock_settings.backup_retention_days = 7
            await run_backup()

        assert existing.read_text() == "dummy"


class TestCleanupOldBackups:
    def test_deletes_old_files(self, tmp_path):
        old_date = date.today() - timedelta(days=10)
        old_file = tmp_path / f"pulse-{old_date.isoformat()}.db"
        old_file.write_text("old")

        recent_date = date.today() - timedelta(days=2)
        recent_file = tmp_path / f"pulse-{recent_date.isoformat()}.db"
        recent_file.write_text("recent")

        with patch("app.backup.settings") as mock_settings:
            mock_settings.backup_retention_days = 7
            cleanup_old_backups(tmp_path)

        assert not old_file.exists()
        assert recent_file.exists()

    def test_ignores_non_matching_files(self, tmp_path):
        other_file = tmp_path / "other.db"
        other_file.write_text("keep me")

        with patch("app.backup.settings") as mock_settings:
            mock_settings.backup_retention_days = 7
            cleanup_old_backups(tmp_path)

        assert other_file.exists()

    def test_handles_empty_directory(self, tmp_path):
        with patch("app.backup.settings") as mock_settings:
            mock_settings.backup_retention_days = 7
            cleanup_old_backups(tmp_path)
