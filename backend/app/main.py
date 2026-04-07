"""FastAPI application for IT Service Health Dashboard."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import close_db, get_db, init_db

logger = logging.getLogger(__name__)

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: DB init, HTTP client, shutdown."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Initialize database and run migrations
    await init_db()

    # Auto-seed services and dependencies (idempotent)
    from app.seed import load_dependencies, load_services, seed_dependencies, seed_services
    services = load_services()
    await seed_services(services)
    deps = load_dependencies()
    await seed_dependencies(deps, [s.id for s in services])

    # Create shared HTTP client for all pollers
    app.state.http_client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
    )

    # Seed demo data if configured
    if settings.seed_demo_data:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from scripts.seed_demo_data import seed_demo_data
        db = await get_db()
        await seed_demo_data(db=db)

    # Start poll scheduler
    from app.poller.scheduler import start_scheduler, stop_scheduler
    start_scheduler(app)

    logger.info("IT Service Health Dashboard v%s started", VERSION)
    yield

    # Shutdown
    stop_scheduler()
    await app.state.http_client.aclose()
    await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="IT Service Health Dashboard",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)

# Register routers
from app.router_admin import router as admin_router  # noqa: E402
from app.router_services import router as services_router  # noqa: E402
from app.router_timeline import router as timeline_router  # noqa: E402
from app.router_summary import router as summary_router  # noqa: E402
from app.router_reports import router as reports_router  # noqa: E402

app.include_router(admin_router)
app.include_router(services_router)
app.include_router(timeline_router)
app.include_router(summary_router)
app.include_router(reports_router)


@app.get("/api/health")
async def health() -> dict:
    """Rich health check: DB connectivity, poll freshness, service counts."""
    health_status = "healthy"
    db_status = "unknown"
    last_poll_at = None
    poll_age_seconds = None
    services_total = 0
    services_polled = 0

    try:
        conn = await get_db()

        # DB connectivity check
        cursor = await conn.execute("SELECT 1")
        await cursor.fetchone()
        db_status = "connected"

        # Service counts
        cursor = await conn.execute("SELECT count(*) FROM services")
        row = await cursor.fetchone()
        services_total = row[0]

        cursor = await conn.execute(
            "SELECT count(*) FROM services WHERE last_polled_at IS NOT NULL"
        )
        row = await cursor.fetchone()
        services_polled = row[0]

        # Last poll timestamp
        cursor = await conn.execute("SELECT MAX(last_polled_at) FROM services")
        row = await cursor.fetchone()
        if row[0]:
            last_poll_at = row[0]
            try:
                poll_time = datetime.fromisoformat(row[0])
                if poll_time.tzinfo is None:
                    poll_time = poll_time.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                poll_age_seconds = int((now - poll_time).total_seconds())

                if poll_age_seconds > 300:
                    health_status = "unhealthy"
                elif poll_age_seconds > 120:
                    health_status = "degraded"
            except (ValueError, TypeError) as e:
                logger.warning("Failed to parse last_poll_at timestamp: %s", e)

    except Exception as e:
        logger.error("Health check failed: %s", e)
        db_status = "error"
        health_status = "unhealthy"

    return {
        "status": health_status,
        "database": db_status,
        "last_poll_at": last_poll_at,
        "poll_age_seconds": poll_age_seconds,
        "services_total": services_total,
        "services_polled": services_polled,
        "version": VERSION,
    }


# Serve built React frontend (production mode)
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="static-assets")

    @app.get("/sw.js")
    async def serve_sw():
        """Serve service worker with no-cache headers for immediate update detection."""
        sw_path = FRONTEND_DIR / "sw.js"
        if sw_path.is_file():
            return FileResponse(
                sw_path,
                media_type="application/javascript",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """SPA catch-all: serve index.html for all non-API routes."""
        file_path = (FRONTEND_DIR / full_path).resolve()
        # Prevent path traversal: ensure resolved path is within FRONTEND_DIR
        if file_path.is_file() and str(file_path).startswith(str(FRONTEND_DIR.resolve())):
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
