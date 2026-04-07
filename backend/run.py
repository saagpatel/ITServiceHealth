"""Entry point for the IT Service Health Dashboard backend.

Usage:
    python run.py          # Production mode (uses HOST/PORT from env, multi-worker)
    python run.py --dev    # Development mode (reload, single worker, verbose logging)
"""

import sys

import uvicorn

from app.config import settings

dev = "--dev" in sys.argv or settings.host == "127.0.0.1"

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=dev,
        workers=1 if dev else 2,
        log_level="info" if dev else "warning",
        timeout_graceful_shutdown=30,
    )
