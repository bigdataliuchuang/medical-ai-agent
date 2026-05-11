"""Structured JSON logger for the Data Agent."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class LogContext:
    """Contextual information attached to log entries."""

    request_id: str = ""
    agent_step: int | None = None
    tool_name: str | None = None
    elapsed_ms: int | None = None


class StructuredLogger:
    """Logger that outputs structured JSON to stderr."""

    def __init__(self, name: str):
        self._name = name
        self._logger = logging.getLogger(name)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log("INFO", event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log("WARNING", event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._log("ERROR", event, **kwargs)

    def with_context(self, ctx: LogContext) -> BoundLogger:
        return BoundLogger(self, ctx)

    def _log(self, level: str, event: str, **kwargs: Any) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "logger": self._name,
            "event": event,
            **kwargs,
        }
        print(json.dumps(entry, ensure_ascii=False, default=str), file=sys.stderr)


class BoundLogger:
    """Logger with pre-bound context fields."""

    def __init__(self, parent: StructuredLogger, ctx: LogContext):
        self._parent = parent
        self._ctx = ctx

    def info(self, event: str, **kwargs: Any) -> None:
        self._parent.info(event, **self._ctx_fields(), **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._parent.warning(event, **self._ctx_fields(), **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._parent.error(event, **self._ctx_fields(), **kwargs)

    def _ctx_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if self._ctx.request_id:
            fields["request_id"] = self._ctx.request_id
        if self._ctx.agent_step is not None:
            fields["agent_step"] = self._ctx.agent_step
        if self._ctx.tool_name is not None:
            fields["tool_name"] = self._ctx.tool_name
        if self._ctx.elapsed_ms is not None:
            fields["elapsed_ms"] = self._ctx.elapsed_ms
        return fields
