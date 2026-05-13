"""Semantic Layer governance persistence."""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


ALLOWED_METRIC_STATUSES = {"draft", "published", "deprecated"}


class SemanticGovernanceError(RuntimeError):
    """Raised when a governance operation is invalid."""


@dataclass(frozen=True)
class MetricStatusOverride:
    metric_name: str
    status: str
    actor: str
    reason: str
    updated_at: float


@dataclass(frozen=True)
class MetricStatusRequest:
    request_id: str
    metric_name: str
    requested_status: str
    requester: str
    reason: str
    status: str
    reviewer: str | None
    comment: str | None
    created_at: float
    reviewed_at: float | None


class SQLiteSemanticGovernanceStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def set_metric_status(
        self,
        metric_name: str,
        status: str,
        actor: str,
        reason: str,
    ) -> MetricStatusOverride:
        if status not in ALLOWED_METRIC_STATUSES:
            raise SemanticGovernanceError(f"Unsupported metric status: {status}")
        override = MetricStatusOverride(
            metric_name=metric_name,
            status=status,
            actor=actor,
            reason=reason,
            updated_at=time.time(),
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO semantic_metric_status (
                    metric_name, status, actor, reason, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(metric_name) DO UPDATE SET
                    status = excluded.status,
                    actor = excluded.actor,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (
                    override.metric_name,
                    override.status,
                    override.actor,
                    override.reason,
                    override.updated_at,
                ),
            )
        return override

    def get_metric_statuses(self) -> dict[str, MetricStatusOverride]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT metric_name, status, actor, reason, updated_at
                FROM semantic_metric_status
                """
            ).fetchall()
        return {
            row["metric_name"]: MetricStatusOverride(
                metric_name=row["metric_name"],
                status=row["status"],
                actor=row["actor"],
                reason=row["reason"],
                updated_at=row["updated_at"],
            )
            for row in rows
        }

    def create_metric_status_request(
        self,
        metric_name: str,
        requested_status: str,
        requester: str,
        reason: str,
    ) -> MetricStatusRequest:
        if requested_status not in ALLOWED_METRIC_STATUSES:
            raise SemanticGovernanceError(f"Unsupported metric status: {requested_status}")
        request = MetricStatusRequest(
            request_id=uuid.uuid4().hex,
            metric_name=metric_name,
            requested_status=requested_status,
            requester=requester,
            reason=reason,
            status="pending",
            reviewer=None,
            comment=None,
            created_at=time.time(),
            reviewed_at=None,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO semantic_metric_status_requests (
                    request_id, metric_name, requested_status, requester, reason,
                    status, reviewer, comment, created_at, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.request_id,
                    request.metric_name,
                    request.requested_status,
                    request.requester,
                    request.reason,
                    request.status,
                    request.reviewer,
                    request.comment,
                    request.created_at,
                    request.reviewed_at,
                ),
            )
        return request

    def list_metric_status_requests(self) -> list[MetricStatusRequest]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT request_id, metric_name, requested_status, requester, reason,
                       status, reviewer, comment, created_at, reviewed_at
                FROM semantic_metric_status_requests
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [_request_from_row(row) for row in rows]

    def review_metric_status_request(
        self,
        request_id: str,
        decision: str,
        reviewer: str,
        comment: str,
    ) -> MetricStatusRequest:
        if decision not in {"approved", "rejected"}:
            raise SemanticGovernanceError(f"Unsupported approval decision: {decision}")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT request_id, metric_name, requested_status, requester, reason,
                       status, reviewer, comment, created_at, reviewed_at
                FROM semantic_metric_status_requests
                WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
            if row is None:
                raise SemanticGovernanceError(f"Unknown metric status request: {request_id}")
            current = _request_from_row(row)
            if current.status != "pending":
                raise SemanticGovernanceError(
                    f"Metric status request is already reviewed: {request_id}"
                )
            reviewed_at = time.time()
            conn.execute(
                """
                UPDATE semantic_metric_status_requests
                SET status = ?, reviewer = ?, comment = ?, reviewed_at = ?
                WHERE request_id = ?
                """,
                (decision, reviewer, comment, reviewed_at, request_id),
            )
        return MetricStatusRequest(
            request_id=current.request_id,
            metric_name=current.metric_name,
            requested_status=current.requested_status,
            requester=current.requester,
            reason=current.reason,
            status=decision,
            reviewer=reviewer,
            comment=comment,
            created_at=current.created_at,
            reviewed_at=reviewed_at,
        )

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_metric_status (
                    metric_name TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_metric_status_requests (
                    request_id TEXT PRIMARY KEY,
                    metric_name TEXT NOT NULL,
                    requested_status TEXT NOT NULL,
                    requester TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reviewer TEXT,
                    comment TEXT,
                    created_at REAL NOT NULL,
                    reviewed_at REAL
                )
                """
            )


def _request_from_row(row: sqlite3.Row) -> MetricStatusRequest:
    return MetricStatusRequest(
        request_id=row["request_id"],
        metric_name=row["metric_name"],
        requested_status=row["requested_status"],
        requester=row["requester"],
        reason=row["reason"],
        status=row["status"],
        reviewer=row["reviewer"],
        comment=row["comment"],
        created_at=row["created_at"],
        reviewed_at=row["reviewed_at"],
    )
