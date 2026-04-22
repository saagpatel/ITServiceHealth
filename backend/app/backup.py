"""SQLite database backup via VACUUM INTO.

Runs as a daily APScheduler job. Creates consistent backups without
blocking writers (WAL mode safe). Rolling retention with automatic cleanup.
"""

import logging
from datetime import date, timedelta
from pathlib import Path

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)


async def run_backup() -> None:
    """Create a daily backup of the SQLite database using VACUUM INTO."""
    try:
        backup_dir = Path(settings.backup_dir).resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)

        backup_path = backup_dir / f"pulse-{date.today().isoformat()}.db"

        # Skip if today's backup already exists
        if backup_path.exists():
            logger.debug("Backup already exists for today: %s", backup_path)
            return

        db = await get_db()
        await db.execute(f"VACUUM INTO '{backup_path}'")

        size_kb = backup_path.stat().st_size / 1024
        logger.info("Database backup created: %s (%.1f KB)", backup_path.name, size_kb)

        cleanup_old_backups(backup_dir)

    except Exception:
        logger.exception("Database backup failed")


def cleanup_old_backups(backup_dir: Path) -> None:
    """Delete backup files older than the configured retention period."""
    cutoff = date.today() - timedelta(days=settings.backup_retention_days)

    for path in backup_dir.glob("pulse-*.db"):
        try:
            # Parse date from filename: pulse-YYYY-MM-DD.db
            file_date = date.fromisoformat(path.stem.removeprefix("pulse-"))
            if file_date < cutoff:
                path.unlink()
                logger.info("Deleted old backup: %s", path.name)
        except (ValueError, OSError):
            # Skip files with unparseable names or deletion errors
            continue
