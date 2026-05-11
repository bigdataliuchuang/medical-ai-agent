"""Production SQL safety guard for Doris queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class SqlGuardDependencyError(RuntimeError):
    """Raised when SQLGlot is not installed in the runtime."""


@dataclass(frozen=True)
class SqlGuardResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)


class SqlGuard:
    def __init__(
        self,
        allowed_schemas: Iterable[str],
        deny_select_star: bool = True,
        require_limit_for_detail_query: bool = True,
    ):
        self.allowed_schemas = {schema.lower() for schema in allowed_schemas}
        self.deny_select_star = deny_select_star
        self.require_limit_for_detail_query = require_limit_for_detail_query

    def validate(self, sql: str) -> SqlGuardResult:
        try:
            import sqlglot
            from sqlglot import exp
        except ModuleNotFoundError as exc:
            raise SqlGuardDependencyError("SQLGlot is required for production SQL validation.") from exc

        reasons: list[str] = []
        tables: list[str] = []

        try:
            parsed = sqlglot.parse(sql, read="mysql")
        except Exception as exc:  # sqlglot exposes several parse exceptions.
            return SqlGuardResult(allowed=False, reasons=[f"SQL parse failed: {exc}"])

        if len(parsed) != 1:
            return SqlGuardResult(allowed=False, reasons=["Only one SQL statement is allowed."])

        statement = parsed[0]
        if not isinstance(statement, exp.Select):
            return SqlGuardResult(allowed=False, reasons=["Only SELECT statements are allowed."])

        if self.deny_select_star and any(
            _is_projected_star(node) for node in statement.walk() if isinstance(node, exp.Star)
        ):
            reasons.append("SELECT * is not allowed.")

        for table in statement.find_all(exp.Table):
            table_name = ".".join(part for part in (table.db, table.name) if part)
            tables.append(table_name)
            if table.db and table.db.lower() not in self.allowed_schemas:
                reasons.append(f"Schema is not allowed: {table.db}")
            if not table.db:
                reasons.append(f"Table must be schema-qualified: {table.name}")

        if self.require_limit_for_detail_query and statement.args.get("limit") is None:
            reasons.append("LIMIT is required for agent-generated SELECT queries.")

        return SqlGuardResult(allowed=not reasons, reasons=reasons, tables=tables)


def _is_projected_star(star: object) -> bool:
    try:
        from sqlglot import exp
    except ModuleNotFoundError as exc:
        raise SqlGuardDependencyError("SQLGlot is required for production SQL validation.") from exc

    parent = getattr(star, "parent", None)
    return isinstance(parent, (exp.Select, exp.Column))
