"""Tests for QueueHandler/QueueListener wiring in configure_logging."""

from __future__ import annotations

import logging
import logging.handlers

import pytest


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Clear root logger handlers after every test to prevent pollution."""
    yield
    logging.getLogger().handlers.clear()


def test_configure_logging_without_file_returns_none(tmp_path):
    from app.logging_config import configure_logging

    result = configure_logging(level="INFO", json_format=True, log_file=None)
    assert result is None


def test_configure_logging_with_file_returns_listener(tmp_path):
    from app.logging_config import configure_logging

    log_file = tmp_path / "app.log"
    listener = configure_logging(level="INFO", json_format=True, log_file=str(log_file))
    assert isinstance(listener, logging.handlers.QueueListener)
    # The listener's wrapped handler must be a WatchedFileHandler
    wrapped = listener.handlers[0]
    assert isinstance(wrapped, logging.handlers.WatchedFileHandler)


def test_log_line_reaches_file_after_listener_start(tmp_path):
    from app.logging_config import configure_logging

    log_file = tmp_path / "app.log"
    listener = configure_logging(level="INFO", json_format=True, log_file=str(log_file))
    assert listener is not None
    listener.start()
    try:
        logging.getLogger("test_logging").info("hello world marker 42")
    finally:
        listener.stop()  # drains the queue before we read the file

    contents = log_file.read_text(encoding="utf-8")
    assert "hello world marker 42" in contents
