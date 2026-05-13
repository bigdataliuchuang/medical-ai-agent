"""Semantic Layer audit events."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any


@dataclass(frozen=True)
class SemanticAuditEvent:
    event_id: str
    event_type: str
    tenant_id: str
    role: str
    status: str
    message: str
    payload: dict[str, Any]
    created_at: float

    @classmethod
    def create(
        cls,
        event_type: str,
        tenant_id: str,
        role: str,
        status: str,
        message: str,
        payload: dict[str, Any],
    ) -> "SemanticAuditEvent":
        return cls(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            tenant_id=tenant_id,
            role=role,
            status=status,
            message=message,
            payload=payload,
            created_at=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemorySemanticAuditStore:
    def __init__(self):
        self._events: list[SemanticAuditEvent] = []

    def append(self, event: SemanticAuditEvent) -> None:
        self._events.append(event)

    def list_events(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]


class SQLiteSemanticAuditStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def append(self, event: SemanticAuditEvent) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO semantic_audit_events (
                    event_id, event_type, tenant_id, role, status, message, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.tenant_id,
                    event.role,
                    event.status,
                    event.message,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.created_at,
                ),
            )

    def list_events(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT event_id, event_type, tenant_id, role, status, message, payload_json, created_at
                FROM semantic_audit_events
                ORDER BY created_at ASC, event_id ASC
                """
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "tenant_id": row["tenant_id"],
                "role": row["role"],
                "status": row["status"],
                "message": row["message"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_audit_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
