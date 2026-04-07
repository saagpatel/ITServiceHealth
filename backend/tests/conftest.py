"""Shared test fixtures for IT Service Health Dashboard tests."""

import pytest
import aiosqlite

from app.database import run_migrations
from app.config import settings


@pytest.fixture
async def db(tmp_path):
    """Provide a fresh in-memory database with migrations applied."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(conn, settings.migrations_dir)
    yield conn
    await conn.close()
