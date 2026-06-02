"""
vani/logging_config.py
──────────────────────
Structured logging for Vani OS using structlog.
Call configure_logging() once at startup (in app.py).
Then in any module:

    from vani.logging_config import get_logger
    log = get_logger(__name__)
    log.info("tool_called", tool="whatsapp_send", duration_ms=42)
"""

import logging
import os
import sys

import structlog


def configure_logging() -> None:
    """
    Call once at startup. Reads VANI_ENV env var:
      - "production"  → JSON output (machine-readable)
      - anything else → pretty console output (human-readable)
    """
    env = os.getenv("VANI_ENV", "development").lower()
    is_prod = env == "production"

    # Shared processors applied to every log entry
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_prod:
        # JSON — parse with any log aggregator (Loki, Datadog, etc.)
        renderer = structlog.processors.JSONRenderer()
    else:
        # Pretty coloured console output for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging so third-party libs (LiveKit, etc.) feed in
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO if is_prod else logging.DEBUG,
    )


def get_logger(name: str = "vani"):
    """Return a bound structlog logger for the given module name."""
    return structlog.get_logger(name)
