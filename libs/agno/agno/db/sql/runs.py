"""Atomic mutations and run filters shared by the SQL run stores."""

import time
from typing import Any, Dict, List, Literal, Optional, Tuple

from sqlalchemy import Table, Text, and_, case, cast, exists, func, literal, or_, select, text, update
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnElement


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


def run_matches(run: Dict[str, Any], stored_status: Optional[str], expected: Dict[str, Any]) -> bool:
    """Whether a stored run has every expected value.

    ``expected`` maps "status" to the run's status, and any other dotted path into the run's data, such
    as "metadata.native_hitl.pending", to the value it must hold.
    """
    from agno.db.utils import canonical_run_status

    for path, value in expected.items():
        if path == "status":
            if canonical_run_status(stored_status or run.get("status")) != canonical_run_status(value):
                return False
            continue
        node: Any = run
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node != value:
            return False
    return True


def apply_run_fields(run: Dict[str, Any], fields: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """The run's data with ``fields`` applied, and its canonical status when ``fields`` sets one."""
    from agno.db.utils import canonical_run_status

    updated = {**run, **fields}
    status = None
    if fields.get("status") is not None:
        status = canonical_run_status(fields["status"])
        updated["status"] = status
    return updated, status


def filter_runs_statement(
    stmt: Any,
    table: Table,
    *,
    status: Any = None,
    before_run_index: Optional[int] = None,
    after_run_index: Optional[int] = None,
    created_after: Optional[int] = None,
    created_before: Optional[int] = None,
    top_level_only: bool = False,
    parent_run_ids: Optional[List[str]] = None,
) -> Any:
    """Apply the ``get_runs`` status, run_index, created_at and parent filters to a runs select."""
    from agno.db.utils import run_status_values

    statuses = run_status_values(status)
    if statuses is not None:
        stmt = stmt.where(table.c.status.in_(statuses))
    if before_run_index is not None:
        stmt = stmt.where(table.c.run_index < before_run_index)
    if after_run_index is not None:
        stmt = stmt.where(table.c.run_index > after_run_index)
    if created_after is not None:
        stmt = stmt.where(table.c.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(table.c.created_at <= created_before)
    if parent_run_ids is not None:
        stmt = stmt.where(table.c.parent_run_id.in_(parent_run_ids))
    if top_level_only:
        stmt = stmt.where(run_is_top_level(table))
    return stmt


def run_is_top_level(table: Table) -> ColumnElement:
    """No parent run in the same session: a null or self parent, or one the session does not hold."""
    parent = table.alias("parent_run")
    return or_(
        table.c.parent_run_id.is_(None),
        table.c.parent_run_id == table.c.run_id,
        ~exists().where(and_(parent.c.run_id == table.c.parent_run_id, parent.c.session_id == table.c.session_id)),
    )


def has_unindexed_runs_statement(sessions_table: Table, runs_table: Optional[Table], session_id: str) -> Any:
    """Select one row of flags: the session still embeds legacy runs, and some run row lacks a run_index."""
    legacy: ColumnElement[Any]
    unindexed: ColumnElement[Any]
    if "runs" in sessions_table.c:
        legacy = (
            select(sessions_table.c.session_id)
            .where(sessions_table.c.session_id == session_id)
            .where(func.coalesce(cast(sessions_table.c.runs, Text), "null").notin_(["null", "[]", '""']))
            .exists()
        )
    else:
        legacy = literal(False)
    if runs_table is not None:
        unindexed = (
            select(runs_table.c.run_id)
            .where(runs_table.c.session_id == session_id, runs_table.c.run_index.is_(None))
            .exists()
        )
    else:
        unindexed = literal(False)
    return select(legacy.label("legacy"), unindexed.label("unindexed"))
