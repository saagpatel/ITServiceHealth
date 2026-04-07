"""Async SQLite database with PRAGMA user_version migration system."""

import asyncio
import logging
import re
from pathlib import Path

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level connection and write lock
_db: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    """Return the shared database connection. Raises if not initialized."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


def get_write_lock() -> asyncio.Lock:
    """Return the write lock for serializing write operations."""
    return _write_lock


async def init_db(db_path: str | None = None) -> aiosqlite.Connection:
    """Initialize database: open connection, set pragmas, run pending migrations."""
    global _db

    path = db_path or settings.database_path
    logger.info("Initializing database at %s", path)

    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row

    # Performance and safety pragmas
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA synchronous=NORMAL")

    # Run pending migrations
    await run_migrations(conn, settings.migrations_dir)

    _db = conn
    logger.info("Database initialized successfully")
    return conn


async def run_migrations(conn: aiosqlite.Connection, migrations_dir: Path | None = None) -> int:
    """Run pending SQL migrations based on PRAGMA user_version.

    Migration files must be named NNNN_description.sql (e.g., 0001_initial_schema.sql).
    The NNNN prefix determines the version number.

    Returns the number of migrations applied.
    """
    mdir = migrations_dir or settings.migrations_dir

    # Get current schema version
    cursor = await conn.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    current_version = row[0] if row else 0

    # Find and sort migration files
    if not mdir.exists():
        logger.warning("Migrations directory not found: %s", mdir)
        return 0

    migration_files: list[tuple[int, Path]] = []
    for sql_file in sorted(mdir.glob("*.sql")):
        match = re.match(r"^(\d+)", sql_file.name)
        if match:
            version = int(match.group(1))
            migration_files.append((version, sql_file))

    migration_files.sort(key=lambda x: x[0])

    # Apply pending migrations
    applied = 0
    for version, sql_file in migration_files:
        if version <= current_version:
            continue

        logger.info("Applying migration %s (version %d → %d)", sql_file.name, current_version, version)
        sql = sql_file.read_text()
        await conn.executescript(sql)
        await conn.execute(f"PRAGMA user_version = {version}")
        await conn.commit()
        current_version = version
        applied += 1

    if applied:
        logger.info("Applied %d migration(s), now at version %d", applied, current_version)
    else:
        logger.debug("Database schema up to date (version %d)", current_version)

    return applied


async def close_db() -> None:
    """Close the shared database connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed")
