"""Async SQLite database with PRAGMA user_version migration system.

Phase 4 production tuning:
- `apply_production_pragmas()` is the single source of truth for every
  pragma we want set on every SQLite connection. Called from init_db()
  and also re-exported so future reader-pool connections can use the
  same factory.
- `checkpoint_wal()` runs a truncating WAL checkpoint — called from the
  daily APScheduler job to stop the -wal file from growing without bound
  and to let retention `DELETE`s actually reclaim disk.
- Retention lives in `app/retention.py` and is driven by the scheduler.
"""

import asyncio
import logging
import re
from pathlib import Path

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level connection and write lock — single writer + serialized-via-SQLite
# reads is enough for current load. A reader pool (aiosqlitepool) is scaffolded
# for the future but not yet consumed by any call site; see PRODUCTION-ROADMAP.md.
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


async def apply_production_pragmas(conn: aiosqlite.Connection) -> None:
    """Set every pragma we want on every SQLite connection.

    Applied once at startup to the shared connection, and also usable as
    a connection factory hook for future reader-pool connections.

    - WAL mode: concurrent reads + single writer, durable across crashes.
    - synchronous=NORMAL + WAL: durable against process crash (not OS
      power loss). Fine for a Mac Mini on UPS/wall power; the
      alternative FULL doubles write latency.
    - busy_timeout=5000: tolerate transient write-lock contention rather
      than immediately failing with SQLITE_BUSY.
    - cache_size=-64000: 64 MB per-connection page cache (negative =
      KB, so -64000 = 64 MB). Cheap and improves read latency for hot
      tables (services, status_events).
    - mmap_size=256 MB: memory-mapped I/O for reads. At our data size
      this fits the whole DB in memory; reads become zero-copy.
    - temp_store=MEMORY: hold intermediate sort/temp data in RAM
      rather than on disk.
    - foreign_keys=ON: enforce referential integrity. Off by default in
      SQLite which is a lurking footgun.
    """
    for stmt in (
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=NORMAL",
        "PRAGMA busy_timeout=5000",
        "PRAGMA cache_size=-64000",
        "PRAGMA mmap_size=268435456",
        "PRAGMA temp_store=MEMORY",
        "PRAGMA foreign_keys=ON",
    ):
        await conn.execute(stmt)


async def init_db(db_path: str | None = None) -> aiosqlite.Connection:
    """Initialize database: open connection, set pragmas, run pending migrations."""
    global _db

    path = db_path or settings.database_path
    logger.info("Initializing database at %s", path)

    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row

    await apply_production_pragmas(conn)

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


async def checkpoint_wal(conn: aiosqlite.Connection | None = None) -> tuple[int, int, int]:
    """Run a TRUNCATE WAL checkpoint to reclaim disk.

    Returns the raw `PRAGMA wal_checkpoint(TRUNCATE)` tuple:
      (busy, pages_in_wal, pages_checkpointed)

    Called from the daily APScheduler job. Without this, the -wal sidecar
    file grows without bound even after DELETE statements run, and disk
    keeps climbing despite retention doing its job.
    """
    target = conn or _db
    if target is None:
        raise RuntimeError("Database not initialized")
    cursor = await target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    row = await cursor.fetchone()
    busy, in_wal, checkpointed = (row[0] or 0), (row[1] or 0), (row[2] or 0)
    logger.info(
        "WAL checkpoint: busy=%d pages_in_wal=%d pages_checkpointed=%d",
        busy, in_wal, checkpointed,
    )
    return busy, in_wal, checkpointed


async def close_db() -> None:
    """Close the shared database connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed")
