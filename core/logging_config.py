"""Structured JSON logging for production observability."""

import json
import logging
import sys
from datetime import datetime, timezone
from contextvars import ContextVar

# Request ID context variable — set per-request by middleware
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class JSONFormatter(logging.Formatter):
    """Emit log records as one JSON line per entry."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        req_id = request_id_var.get("")
        if req_id:
            log_entry["request_id"] = req_id

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Carry structured extras from middleware / route handlers
        for key in ("status_code", "method", "path", "duration_ms", "client_ip"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        return json.dumps(log_entry, ensure_ascii=False)


class ReadableFormatter(logging.Formatter):
    """Human-friendly formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = request_id_var.get("")
        rid = f" [{req_id}]" if req_id else ""
        return (
            f"{datetime.now().strftime('%H:%M:%S')} "
            f"{record.levelname:<8}{rid} "
            f"{record.name} — {record.getMessage()}"
        )


def setup_logging(*, level: str = "INFO", json_format: bool = True) -> None:
    """Configure application logging.

    Args:
        level:      Log level name (DEBUG, INFO, WARNING, ERROR).
        json_format: True → JSON lines (production); False → readable (dev).
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers to avoid duplicate output on reload
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter() if json_format else ReadableFormatter())
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
