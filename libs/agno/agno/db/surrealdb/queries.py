from textwrap import dedent
from typing import Any, Final, Literal

CREATE_TABLE_QUERY: Final[str] = dedent("""
    DEFINE TABLE IF NOT EXISTS {table} SCHEMAFUL;

    DEFINE FIELD IF NOT EXISTS memory ON {table} FLEXIBLE TYPE object;
    DEFINE FIELD IF NOT EXISTS user ON {table} TYPE record<user>;
    DEFINE FIELD IF NOT EXISTS time ON {table} TYPE object DEFAULT ALWAYS {{}};
    DEFINE FIELD IF NOT EXISTS time.created_at ON {table} TYPE datetime VALUE time::now() READONLY;
    DEFINE FIELD IF NOT EXISTS time.updated_at ON {table} TYPE datetime VALUE time::now() READONLY;

    DEFINE INDEX IF NOT EXISTS idx_{table}_user ON {table} FIELDS user;
""")


OPERATOR = Literal["=", "!=", "<=", ">=", "~", "IN", "CONTAINSANY"]

COUNT_QUERY: Final[str] = dedent("""
    RETURN (
        SELECT count(id) AS count
        FROM {table}
        {where_clause}
        {group_clause}
    )[0] OR {{count: 0}}
""")


class WhereClause:
    def __init__(self):
        self._conditions = []
        self._params = {}
        self._param_count = 0

    def _add_filter(self, field: str, operator: str, value: Any):
        param_name = f"p{self._param_count}"
        self._params[param_name] = value
        self._param_count += 1

        condition = f"{field} {operator} ${param_name}"
        if not self._conditions:
            self._conditions.append(condition)
        else:
            self._conditions.append("AND")
            self._conditions.append(condition)
        return self

    def and_(self, field: str, value: Any, operator: OPERATOR = "="):
        return self._add_filter(field, operator, value)

    def build(self) -> tuple[str, dict[str, Any]]:
        if not self._conditions:
            return "", {}
        return "WHERE " + " ".join(self._conditions), self._params


def order_limit_start(
    sort_by: str | None = None, sort_order: str | None = None, limit: int | None = None, page: int | None = None
) -> str:
    order_clause = f"ORDER BY {sort_by} {sort_order or ''}" if sort_by is not None else ""
    limit_clause = f"LIMIT {limit}" if limit is not None else ""
    start_clause = f"START {page * limit}" if page is not None and limit is not None else ""
    return f"{order_clause} {limit_clause} {start_clause}"
