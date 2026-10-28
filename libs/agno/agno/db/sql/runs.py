"""Atomic mutations shared by the SQL run stores."""

import time
from typing import Literal, Optional

from sqlalchemy import Table, Text, case, cast, func, literal, or_, text, update
from sqlalchemy.sql.dml import Update


def cancel_pending_run_statement(
    table: Table,
    dialect: Literal["postgresql", "sqlite"],
    run_id: str,
    session_id: str,
    reason: str,
    user_id: Optional[str],
    expected_status: str = "PENDING",
) -> Update:
    """Keep the status predicate and JSON patch inside one database write."""
    if expected_status not in {"PENDING", "RUNNING"}:
        raise ValueError("Only Pending or Running runs can be cancelled by recovery")
    data = table.c.run_data
    content = data["content"].as_string()
    if dialect == "postgresql":
        cancelled = func.jsonb_set(data, text("'{status}'"), func.to_jsonb(literal("CANCELLED", type_=Text)))
        explained = func.jsonb_set(cancelled, text("'{content}'"), func.to_jsonb(cast(literal(reason), Text)))
    else:
        cancelled = func.json_set(data, "$.status", "CANCELLED")
        explained = func.json_set(cancelled, "$.content", reason)
    return (
        update(table)
        .where(table.c.run_id == run_id, table.c.session_id == session_id, table.c.status == expected_status)
        .where((table.c.user_id == user_id) | table.c.user_id.is_(None))
        .values(
            status="CANCELLED",
            run_data=case((or_(content.is_(None), content == ""), explained), else_=cancelled),
            updated_at=int(time.time()),
        )
        .returning(table.c.run_id)
    )
