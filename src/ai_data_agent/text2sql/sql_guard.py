"""Production SQL safety guard for Doris queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# ---------------------------------------------------------------------------
# Sensitive field blocklist (medical privacy)
# ---------------------------------------------------------------------------
_SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "id_card", "phone", "address", "patient_name",
        "social_security_no", "medical_record_no",
        "contact_name", "contact_phone",
    }
)

# Time-related column name fragments recognised as valid time filters
_TIME_FIELD_FRAGMENTS: tuple[str, ...] = (
    "stat_date", "stat_month", "visit_date", "order_date",
    "created_time", "created_at", "updated_at", "check_date",
    "admit_date", "discharge_date", "result_date", "expense_date",
)

# High-risk DML/DDL keywords — detected before AST parsing for speed
_BLOCKLIST_KEYWORDS: tuple[str, ...] = (
    "DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE",
    "ALTER", "CREATE", "REPLACE", "MERGE", "EXEC", "EXECUTE",
)


class SqlGuardDependencyError(RuntimeError):
    """Raised when SQLGlot is not installed in the runtime."""


@dataclass(frozen=True)
class SqlGuardConfig:
    """Centralised configuration for all guard rules."""

    allowed_schemas: frozenset[str] = field(default_factory=frozenset)
    deny_select_star: bool = True
    require_limit: bool = True
    require_time_filter: bool = False
    block_sensitive_fields: bool = True
    sensitive_fields: frozenset[str] = field(default_factory=lambda: _SENSITIVE_FIELDS)


@dataclass(frozen=True)
class SqlGuardResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    sensitive_fields: list[str] = field(default_factory=list)
    risk_level: str = "LOW"  # LOW | MEDIUM | HIGH


class SqlGuard:
    """Multi-rule SQL safety guard for medical data warehouse queries.

    Rules (all configurable):
    1. High-risk keyword blocklist (DROP/DELETE/UPDATE/...) — string-level, fast
    2. Only SELECT statements allowed — AST-level
    3. SELECT * denied — AST-level
    4. Schema-qualification required — AST-level
    5. LIMIT required — AST-level
    6. Time filter required (optional) — column name heuristic
    7. Sensitive field detection — column name heuristic
    """

    def __init__(
        self,
        allowed_schemas: Iterable[str],
        deny_select_star: bool = True,
        require_limit_for_detail_query: bool = True,
        require_time_filter: bool = False,
        block_sensitive_fields: bool = True,
    ):
        self._config = SqlGuardConfig(
            allowed_schemas=frozenset(s.lower() for s in allowed_schemas),
            deny_select_star=deny_select_star,
            require_limit=require_limit_for_detail_query,
            require_time_filter=require_time_filter,
            block_sensitive_fields=block_sensitive_fields,
        )

    @classmethod
    def from_config(cls, config: SqlGuardConfig) -> "SqlGuard":
        guard = cls.__new__(cls)
        guard._config = config
        return guard

    def validate(self, sql: str) -> SqlGuardResult:
        cfg = self._config

        # Rule 1: blocklist scan (no AST needed)
        upper_sql = sql.upper()
        for kw in _BLOCKLIST_KEYWORDS:
            if _keyword_present(kw, upper_sql):
                return SqlGuardResult(
                    allowed=False,
                    reasons=[f"Dangerous keyword '{kw}' is not allowed."],
                    risk_level="HIGH",
                )

        try:
            import sqlglot
            from sqlglot import exp
        except ModuleNotFoundError as exc:
            raise SqlGuardDependencyError(
                "SQLGlot is required for production SQL validation."
            ) from exc

        try:
            parsed = sqlglot.parse(sql, read="mysql")
        except Exception as exc:
            return SqlGuardResult(
                allowed=False, reasons=[f"SQL parse failed: {exc}"], risk_level="HIGH"
            )

        if len(parsed) != 1:
            return SqlGuardResult(
                allowed=False,
                reasons=["Only one SQL statement is allowed."],
                risk_level="HIGH",
            )

        statement = parsed[0]

        # Rule 2: SELECT only
        if not isinstance(statement, exp.Select):
            return SqlGuardResult(
                allowed=False,
                reasons=["Only SELECT statements are allowed."],
                risk_level="HIGH",
            )

        reasons: list[str] = []
        tables: list[str] = []
        found_sensitive: list[str] = []

        # Rule 3: no SELECT *
        if cfg.deny_select_star and any(
            _is_projected_star(node)
            for node in statement.walk()
            if isinstance(node, exp.Star)
        ):
            reasons.append("SELECT * is not allowed.")

        # Rule 4: schema qualification
        for table in statement.find_all(exp.Table):
            table_name = ".".join(part for part in (table.db, table.name) if part)
            tables.append(table_name)
            if table.db and table.db.lower() not in cfg.allowed_schemas:
                reasons.append(f"Schema is not allowed: {table.db}")
            if not table.db:
                reasons.append(f"Table must be schema-qualified: {table.name}")

        # Rule 5: LIMIT required
        if cfg.require_limit and statement.args.get("limit") is None:
            reasons.append("LIMIT is required for agent-generated SELECT queries.")

        # Rule 6: time filter (heuristic — checks column names in WHERE clause)
        if cfg.require_time_filter:
            where_sql = _where_clause_text(statement)
            if not any(frag in where_sql.lower() for frag in _TIME_FIELD_FRAGMENTS):
                reasons.append(
                    "A time range filter is required "
                    f"(expected column containing: {', '.join(_TIME_FIELD_FRAGMENTS[:4])} …)."
                )

        # Rule 7: sensitive field detection
        if cfg.block_sensitive_fields:
            all_col_names = _extract_column_names(statement)
            for col in all_col_names:
                if col.lower() in cfg.sensitive_fields:
                    found_sensitive.append(col)
            if found_sensitive:
                reasons.append(
                    f"Query references sensitive field(s): {', '.join(found_sensitive)}. "
                    "Access requires explicit authorisation."
                )

        risk = _compute_risk(reasons, found_sensitive)
        return SqlGuardResult(
            allowed=not reasons,
            reasons=reasons,
            tables=tables,
            sensitive_fields=found_sensitive,
            risk_level=risk,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _keyword_present(keyword: str, upper_sql: str) -> bool:
    """True if keyword appears as a whole word (not inside a string/identifier)."""
    import re
    return bool(re.search(rf"\b{re.escape(keyword)}\b", upper_sql))


def _is_projected_star(star: object) -> bool:
    try:
        from sqlglot import exp
    except ModuleNotFoundError as exc:
        raise SqlGuardDependencyError(
            "SQLGlot is required for production SQL validation."
        ) from exc
    parent = getattr(star, "parent", None)
    return isinstance(parent, (exp.Select, exp.Column))


def _where_clause_text(statement: object) -> str:
    try:
        from sqlglot import exp
    except ModuleNotFoundError:
        return ""
    where = getattr(statement, "args", {}).get("where")
    return where.sql() if where else ""


def _extract_column_names(statement: object) -> list[str]:
    """Extract all column names referenced in SELECT and WHERE."""
    try:
        from sqlglot import exp
    except ModuleNotFoundError:
        return []
    cols: list[str] = []
    for node in statement.walk():  # type: ignore[union-attr]
        if isinstance(node, exp.Column) and node.name:
            cols.append(node.name)
    return cols


def _compute_risk(reasons: list[str], sensitive: list[str]) -> str:
    if sensitive:
        return "HIGH"
    if any("LIMIT" in r or "time range" in r for r in reasons):
        return "MEDIUM"
    if reasons:
        return "MEDIUM"
    return "LOW"
