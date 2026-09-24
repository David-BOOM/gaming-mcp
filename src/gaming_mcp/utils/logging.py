"""Structured JSON logging and diagnostics for gaming-mcp server."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class StructuredFormatter(logging.Formatter):
    """Formats log records as newline-delimited JSON objects to sys.stderr."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "adapter_id"):
            log_entry["adapter_id"] = record.adapter_id
        if hasattr(record, "tool_name"):
            log_entry["tool_name"] = record.tool_name
        if hasattr(record, "latency_ms"):
            log_entry["latency_ms"] = record.latency_ms
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging(level_name: str = "INFO", structured: bool = True) -> logging.Logger:
    """Configure root logger to output to sys.stderr to avoid stdio pollution."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    root_logger = logging.getLogger("gaming_mcp")
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    if structured:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
        )

    root_logger.addHandler(handler)
    return root_logger
