"""Atomic sandbox registry statements for PostgreSQL and SQLite.

Every replacement requires the revision read by the caller. An insert never
replaces an existing session binding. Database time is returned alongside reads
so lifecycle leases do not depend on control-plane clocks agreeing.
"""

from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, cast, delete, func, select, update


def database_time(dialect: str) -> Any:
    if dialect == "postgresql":
        return cast(func.extract("epoch", func.now()), BigInteger)
    return cast(func.strftime("%s", "now"), BigInteger)


def write_statement(table: Any, dialect: str, record: Dict[str, Any], expected_revision: Optional[int]) -> Any:
    values = {key: value for key, value in record.items() if key in table.c}
    values["updated_at"] = database_time(dialect)
    if expected_revision is None:
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert  # type: ignore[assignment]
        values.update(revision=1, created_at=database_time(dialect), last_active_at=database_time(dialect))
        return insert(table).values(**values).on_conflict_do_nothing().returning(table.c.sandbox_id)
    sandbox_id = values.pop("sandbox_id")
    # Session identity and ownership are immutable for the lifetime of a binding.
    for key in ("session_id", "agent_id", "user_id", "provider", "created_at"):
        values.pop(key, None)
    values["revision"] = expected_revision + 1
    return (
        update(table)
        .where(table.c.sandbox_id == sandbox_id, table.c.revision == expected_revision)
        .values(**values)
        .returning(table.c.sandbox_id)
    )


def read_statement(
    table: Any,
    dialect: str,
    sandbox_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Any:
    stmt = select(table, database_time(dialect).label("db_now"))
    for key, value in dict(
        sandbox_id=sandbox_id, session_id=session_id, agent_id=agent_id, user_id=user_id, status=status
    ).items():
        if value is not None:
            stmt = stmt.where(table.c[key] == value)
    return stmt.order_by(table.c.created_at, table.c.sandbox_id)


def delete_statement(table: Any, sandbox_id: str, expected_revision: int) -> Any:
    # Live bindings must be destroyed through the provider before removal.
    return (
        delete(table)
        .where(
            table.c.sandbox_id == sandbox_id,
            table.c.revision == expected_revision,
            table.c.status == "destroyed",
            table.c.active_run_id.is_(None),
        )
        .returning(table.c.sandbox_id)
    )
