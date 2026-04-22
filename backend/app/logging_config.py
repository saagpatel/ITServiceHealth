"""Structured logging setup for the IT Service Health Dashboard.

Configures structlog to output JSON (production) or a pretty console
renderer (development), with contextvars integration so values bound
via ``structlog.contextvars.bind_contextvars(poll_cycle_id=...)`` follow
the log line through every module that logs during that poll cycle.

Backward compat: stdlib ``logging.getLogger(__name__)`` calls still
work — they're piped through structlog's ``ProcessorFormatter`` so they
emit the same JSON shape as native structlog calls. Existing ``logger =
logging.getLogger(__name__)`` in every module keeps working without a
rewrite.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(
    level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Set up structlog + stdlib logging as a unified JSON pipeline.

    Call once at app startup (lifespan). Safe to re-invoke — idempotent.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Shared processors that run before the final formatter. `merge_contextvars`
    # is the key piece — it pulls in anything bound via bind_contextvars().
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_format:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    # Configure structlog's native logger factory
    structlog.configure(
        processors=[
            *shared_processors,
            # ProcessorFormatter.wrap_for_formatter must be the LAST processor
            # when piping through stdlib — it serializes the event dict for
            # the stdlib handler to re-render via ProcessorFormatter.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to pipe *everything* (including third-party
    # libraries like httpx/uvicorn) through our structlog formatter.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace any existing handlers to avoid duplicate output when the
    # lifespan is re-entered (e.g., during tests using the FastAPI TestClient).
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # Quiet down chatty third-party loggers one notch
    for noisy in ("httpx", "httpcore", "apscheduler"):
        logging.getLogger(noisy).setLevel(max(numeric_level, logging.WARNING))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Convenience accessor for structlog loggers.

    Most modules should keep using ``logging.getLogger(__name__)`` for
    stdlib-compat. Use this when you want structlog-native features like
    ``.bind()`` for per-call context.
    """
    return structlog.get_logger(name)
