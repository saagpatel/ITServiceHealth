"""Scheduler result handling with local database state and an offline poller."""

import asyncio

import httpx
import pytest
import structlog
from fastapi import FastAPI

from app.poller import scheduler
from app.poller.normalizer import ServiceStatus
from app.poller.statuspage_poller import PollResult


@pytest.mark.parametrize("cancelled", [False, True])
async def test_poll_cycle_preserves_results_and_cancellation(db, monkeypatch, cancelled):
    await db.execute(
        """INSERT INTO services
           (id, display_name, category, poll_type, poll_url, current_status)
           VALUES ('test', 'Test', 'other', 'current_status_api',
                   'https://example.invalid/status', 'operational')"""
    )
    await db.commit()

    async def get_db():
        return db

    async def offline_poll(client, url):
        if cancelled:
            raise asyncio.CancelledError("poll cancelled")
        return PollResult(status=ServiceStatus.OPERATIONAL)

    monkeypatch.setattr(scheduler, "get_db", get_db)
    monkeypatch.setattr(scheduler, "get_write_lock", lambda: asyncio.Lock())
    monkeypatch.setattr("app.poller.current_status_poller.poll_current_status", offline_poll)
    app = FastAPI()
    async with httpx.AsyncClient() as client:
        app.state.http_client = client
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await scheduler.run_poll_cycle(app)
        else:
            await scheduler.run_poll_cycle(app)
            cursor = await db.execute("SELECT last_polled_at FROM services WHERE id = 'test'")
            row = await cursor.fetchone()
            assert row[0] is not None

    assert "poll_cycle_id" not in structlog.contextvars.get_contextvars()
