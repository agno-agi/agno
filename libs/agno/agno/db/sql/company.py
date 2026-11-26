"""Company archive transactions shared by the SQL adapters.

The adapters resolve tables and own the transaction. Async adapters use
AsyncSession.run_sync, so these same statements execute through their async driver.
Archive provenance lives in the existing JSON transition history, leaving lifecycle
status intact. Only the last archive event may authorize a cascading restore.
"""

import time
from typing import Any, Dict, List, Optional

from sqlalchemy import func, literal, or_, select, union_all

from agno.db.schemas.company import validate_company_details
from agno.db.schemas.projects import is_default_project, refuse_default_project
from agno.db.schemas.tasks import (
    OPEN_TASK_STATUSES,
    CancelledProjectError,
    OpenTaskLimitError,
    task_context_after,
)


def active_parents(stmt: Any, table: Any, goals: Any, projects: Any = None) -> Any:
    """Hide children of archived parents before counting or paging. A record with no Goal has none to hide it."""
    stmt = stmt.where(
        or_(
            table.c.goal_id.is_(None),
            select(goals.c.id).where(goals.c.id == table.c.goal_id, goals.c.deleted_at.is_(None)).exists(),
        )
    )
    if projects is not None:
        stmt = stmt.where(
            or_(
                table.c.project_id.is_(None),
                select(projects.c.id)
                .where(projects.c.id == table.c.project_id, projects.c.deleted_at.is_(None))
                .exists(),
            )
        )
    return stmt


def lock_goal(sess: Any, goals: Any, goal_id: str) -> None:
    """Serialize hierarchy writes on the Goal, including on SQLite.

    A no-op UPDATE obtains a write lock without changing the activity timestamp.
    Every child creation, move, transition and restore shares this lock with archive.
    """
    stmt = goals.update().where(goals.c.id == goal_id, goals.c.deleted_at.is_(None))
    row = sess.execute(stmt.values(updated_at=goals.c.updated_at).returning(goals.c.id)).first()
    if row is None:
        raise ValueError("Goal is missing or archived")


def lock_parent(sess: Any, goals: Any, projects: Any, goal_id: Optional[str], project_id: Optional[str] = None) -> None:
    """Serialize a hierarchy write on the record's Goal, or on its Project when the record has no Goal.

    A Project and its Tasks with no Goal share the Project's row as their lock, the way records
    of a Goal share the Goal's row. A new Project with no Goal has nothing to wait for.
    """
    if goal_id is not None:
        lock_goal(sess, goals, goal_id)
    elif project_id is not None:
        sess.execute(projects.update().where(projects.c.id == project_id).values(updated_at=projects.c.updated_at))


def require_open_room(sess: Any, tasks: Any, task_id: str, auto_accept: Dict[str, Any]) -> None:
    """Refuse an automatic acceptance when its Routine already has max_open Tasks open.

    The caller holds the Goal lock, so two acceptances cannot both count a free place.
    A receipt with no max_open is not counted.
    """
    limit = auto_accept.get("max_open")
    if limit is None:
        return
    open_now = sess.execute(
        select(func.count())
        .select_from(tasks)
        .where(
            tasks.c.routine_id == auto_accept["routine_id"],
            tasks.c.id != task_id,
            tasks.c.status.in_(OPEN_TASK_STATUSES),
            tasks.c.deleted_at.is_(None),
        )
    ).scalar()
    if (open_now or 0) >= limit:
        raise OpenTaskLimitError(
            f"Routine has {open_now} Tasks open, its limit. Complete or cancel one for it to accept more"
        )


def require_project(
    sess: Any,
    projects: Any,
    project_id: Optional[str],
    goal_id: Optional[str],
    task_status: Optional[str] = None,
    *,
    reject_proposed: bool = False,
    reject_cancelled: bool = False,
) -> None:
    if project_id is None:
        return
    if goal_id is None:
        # No Goal row serializes this write with the Project's own transitions, so the Project is
        # locked before it is read. A move then cannot land in a Project that completes meanwhile.
        lock_parent(sess, None, projects, None, project_id)
    row = sess.execute(select(projects).where(projects.c.id == project_id)).first()
    if row is None or row._mapping["deleted_at"] is not None:
        raise ValueError("Project is missing or archived")
    # A Task carries its Project's Goal, or none when the Project has none. The Default Project
    # holds Tasks of any Goal and of none.
    if not is_default_project(project_id) and row._mapping["goal_id"] != goal_id:
        raise ValueError("Task and Project must belong to the same Goal")
    if reject_cancelled and row._mapping["status"] == "cancelled":
        raise CancelledProjectError("Cannot change Task status in a cancelled Project")
    if reject_proposed and row._mapping["status"] == "proposed":
        raise ValueError("Project approval is required before creating Tasks outside Backlog or moving them to Ready")
    if (
        task_status is not None
        and task_status not in {"done", "cancelled"}
        and row._mapping["status"] in {"done", "cancelled"}
    ):
        raise ValueError("Cannot add open work to a completed or cancelled Project")


def existing_task_proposal(sess: Any, tasks: Any, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A completed proposal remains idempotent even after its Project is completed."""
    if data.get("dedupe_key") is None:
        return None
    row = sess.execute(
        select(tasks).where(tasks.c.goal_id == data["goal_id"], tasks.c.dedupe_key == data["dedupe_key"])
    ).first()
    return dict(row._mapping) if row is not None else None


def lock_child(
    sess: Any,
    goals: Any,
    projects: Any,
    table: Any,
    record_id: str,
    restoring: bool = False,
    reject_cancelled: bool = False,
) -> None:
    """Restoring checks the record's own status, so hidden open work cannot re-enter a terminal Project."""
    row = sess.execute(select(table).where(table.c.id == record_id)).first()
    if row is None:
        return
    record = row._mapping
    lock_parent(
        sess, goals, projects, record["goal_id"], record["project_id"] if "project_id" in table.c else record_id
    )
    # Read the Project again after taking the Goal lock: a move may have won it.
    if "project_id" in table.c:
        row = sess.execute(select(table).where(table.c.id == record_id)).one()
        status = row._mapping["status"] if restoring else None
        require_project(
            sess, projects, row._mapping["project_id"], record["goal_id"], status, reject_cancelled=reject_cancelled
        )


def change_task_context(
    sess: Any,
    goals: Any,
    projects: Any,
    tasks: Any,
    task_id: str,
    add: Optional[List[Dict[str, Any]]],
    remove: Optional[List[str]],
    expected_status: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Change a Task's context list under the lock its other writes take, so two changes never lose one."""
    lock_child(sess, goals, projects, tasks, task_id)
    row = sess.execute(select(tasks).where(tasks.c.id == task_id, tasks.c.deleted_at.is_(None))).first()
    if row is None or (expected_status is not None and row._mapping["status"] != expected_status):
        return None
    context = task_context_after(dict(row._mapping), add, remove)
    stmt = tasks.update().where(tasks.c.id == task_id).values(context=context, updated_at=int(time.time()))
    return dict(sess.execute(stmt.returning(tasks)).one()._mapping)


def open_project_tasks(tasks: Any, project_id: str) -> Any:
    """Visible non-terminal Tasks keep a Project from finishing or retiring; archived ones are hidden everywhere."""
    return select(tasks).where(
        tasks.c.project_id == project_id,
        tasks.c.deleted_at.is_(None),
        tasks.c.status.not_in(["done", "cancelled"]),
    )


def _event(record: Dict[str, Any], action: str, now: int, parent: Optional[Dict[str, str]] = None) -> Any:
    return [
        *(record.get("transitions") or []),
        {
            "action": action,
            "from": record["status"],
            "target": record["status"],
            "reason": "Parent archived" if parent else ("Archived" if action == "archive" else "Restored"),
            "created_at": now,
            "user_id": None,
            "archived_by": parent,
        },
    ]


def task_restore_fields(record: Dict[str, Any]) -> Dict[str, Any]:
    """Close a cascade event without changing standalone Task acceptance history.

    Ordinary Task archive only changes deleted_at. Its restore must also leave
    lifecycle history intact because queued execution fences against that history.
    """
    now = int(time.time())
    fields: Dict[str, Any] = {"deleted_at": None, "updated_at": now}
    history = record.get("transitions") or []
    if history and history[-1].get("action") == "archive":
        fields["transitions"] = _event(record, "restore", now)
    return fields


def _archive_children(sess: Any, table: Any, condition: Any, parent: Dict[str, str], now: int) -> None:
    rows = sess.execute(select(table).where(condition, table.c.deleted_at.is_(None))).mappings().all()
    for row in rows:
        sess.execute(
            table.update()
            .where(table.c.id == row["id"])
            .values(deleted_at=now, updated_at=now, transitions=_event(dict(row), "archive", now, parent))
        )


def _restore_children(sess: Any, table: Any, condition: Any, parent: Dict[str, str], now: int) -> None:
    rows = sess.execute(select(table).where(condition, table.c.deleted_at.is_not(None))).mappings().all()
    for row in rows:
        history = row["transitions"] or []
        if not history or history[-1].get("action") != "archive" or history[-1].get("archived_by") != parent:
            continue
        sess.execute(
            table.update()
            .where(table.c.id == row["id"])
            .values(deleted_at=None, updated_at=now, transitions=_event(dict(row), "restore", now))
        )


def _refuse_open_tasks(sess: Any, tasks: Any, condition: Any) -> None:
    # Archived Tasks are hidden from lists and counts, so they must not block either.
    rows = (
        sess.execute(
            select(tasks.c.id, tasks.c.title)
            .where(
                condition,
                tasks.c.deleted_at.is_(None),
                tasks.c.status.in_(["ready", "in_progress", "in_review"]),
            )
            .order_by(tasks.c.id)
        )
        .mappings()
        .all()
    )
    if rows:
        raise ValueError({"message": "Cannot archive with active Tasks", "tasks": [dict(row) for row in rows]})


def archive_goal(sess: Any, goals: Any, projects: Any, tasks: Any, goal_id: str, user_id: Optional[str]) -> bool:
    stmt = goals.update().where(goals.c.id == goal_id, goals.c.deleted_at.is_(None))
    if user_id is not None:
        stmt = stmt.where(goals.c.user_id == user_id)
    now = int(time.time())
    # Lock and change the parent first; a refusal rolls back the whole transaction.
    if sess.execute(stmt.values(deleted_at=now, updated_at=now).returning(goals.c.id)).first() is None:
        return False
    _refuse_open_tasks(sess, tasks, tasks.c.goal_id == goal_id)
    parent = {"type": "goal", "id": goal_id}
    _archive_children(sess, projects, projects.c.goal_id == goal_id, parent, now)
    _archive_children(sess, tasks, tasks.c.goal_id == goal_id, parent, now)
    return True


def restore_goal(
    sess: Any, goals: Any, projects: Any, tasks: Any, goal_id: str, user_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    stmt = goals.update().where(goals.c.id == goal_id, goals.c.deleted_at.is_not(None))
    if user_id is not None:
        stmt = stmt.where(goals.c.user_id == user_id)
    now = int(time.time())
    row = sess.execute(stmt.values(deleted_at=None, updated_at=now).returning(goals)).first()
    if row is None:
        return None
    parent = {"type": "goal", "id": goal_id}
    _restore_children(sess, projects, projects.c.goal_id == goal_id, parent, now)
    _restore_children(sess, tasks, tasks.c.goal_id == goal_id, parent, now)
    return dict(row._mapping)


def archive_project(
    sess: Any,
    goals: Any,
    projects: Any,
    tasks: Any,
    project_id: str,
    user_id: Optional[str],
    updated_before: Optional[int] = None,
) -> bool:
    refuse_default_project(project_id, "archive")
    lock_child(sess, goals, projects, projects, project_id)
    stmt = select(projects).where(projects.c.id == project_id, projects.c.deleted_at.is_(None))
    if user_id is not None:
        stmt = stmt.where(projects.c.user_id == user_id)
    if updated_before is not None:
        stmt = stmt.where(
            projects.c.status.in_(["done", "cancelled"]),
            func.coalesce(projects.c.updated_at, projects.c.created_at) < updated_before,
        )
    row = sess.execute(stmt).first()
    if row is None:
        return False
    _refuse_open_tasks(sess, tasks, tasks.c.project_id == project_id)
    if updated_before is not None and sess.execute(open_project_tasks(tasks, project_id)).first() is not None:
        return False
    now = int(time.time())
    sess.execute(
        projects.update()
        .where(projects.c.id == project_id)
        .values(deleted_at=now, updated_at=now, transitions=_event(dict(row._mapping), "archive", now))
    )
    _archive_children(sess, tasks, tasks.c.project_id == project_id, {"type": "project", "id": project_id}, now)
    return True


def restore_project(
    sess: Any, goals: Any, projects: Any, tasks: Any, project_id: str, user_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    lock_child(sess, goals, projects, projects, project_id)
    stmt = select(projects).where(projects.c.id == project_id, projects.c.deleted_at.is_not(None))
    if user_id is not None:
        stmt = stmt.where(projects.c.user_id == user_id)
    row = sess.execute(stmt).first()
    if row is None:
        return None
    now = int(time.time())
    restored = sess.execute(
        projects.update()
        .where(projects.c.id == project_id)
        .values(deleted_at=None, updated_at=now, transitions=_event(dict(row._mapping), "restore", now))
        .returning(projects)
    ).one()
    _restore_children(sess, tasks, tasks.c.project_id == project_id, {"type": "project", "id": project_id}, now)
    return dict(restored._mapping)


def goal_counts(sess: Any, goals: Any, projects: Any, tasks: Any, goal_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """One grouped SQL statement for both kinds of child on a Goal page."""
    from agno.db.schemas.tasks import TASK_TRANSITIONS

    counts: Dict[str, Dict[str, Any]] = {
        pid: {"projects": 0, "tasks": dict.fromkeys(TASK_TRANSITIONS, 0)} for pid in goal_ids
    }
    if not goal_ids:
        return counts
    project_query = active_parents(
        select(projects.c.goal_id.label("parent_id"), literal("projects").label("kind"), func.count().label("total"))
        .where(
            projects.c.goal_id.in_(goal_ids),
            projects.c.deleted_at.is_(None),
            projects.c.status.in_(["proposed", "active"]),
        )
        .group_by(projects.c.goal_id),
        projects,
        goals,
    )
    task_query = active_parents(
        select(tasks.c.goal_id.label("parent_id"), tasks.c.status.label("kind"), func.count().label("total"))
        .where(tasks.c.goal_id.in_(goal_ids), tasks.c.deleted_at.is_(None))
        .group_by(tasks.c.goal_id, tasks.c.status),
        tasks,
        goals,
        projects,
    )
    for row in sess.execute(union_all(project_query, task_query)).mappings():
        if row["kind"] == "projects":
            counts[row["parent_id"]]["projects"] = row["total"]
        else:
            counts[row["parent_id"]]["tasks"][row["kind"]] = row["total"]
    return counts


def project_counts(
    sess: Any, goals: Any, projects: Any, tasks: Any, project_ids: List[str]
) -> Dict[str, Dict[str, Any]]:
    """One grouped SQL statement for all Task statuses on a Project page."""
    from agno.db.schemas.tasks import TASK_TRANSITIONS

    counts: Dict[str, Dict[str, Any]] = {pid: {"tasks": dict.fromkeys(TASK_TRANSITIONS, 0)} for pid in project_ids}
    if not project_ids:
        return counts
    query = active_parents(
        select(tasks.c.project_id, tasks.c.status, func.count().label("total"))
        .where(tasks.c.project_id.in_(project_ids), tasks.c.deleted_at.is_(None))
        .group_by(tasks.c.project_id, tasks.c.status),
        tasks,
        goals,
        projects,
    )
    for row in sess.execute(query).mappings():
        counts[row["project_id"]]["tasks"][row["status"]] = row["total"]
    return counts


def create_company_source(
    sess: Any, goals: Any, table: Any, source_data: Dict[str, Any], reuse: bool
) -> Dict[str, Any]:
    """Serialize Source additions with Goal archives and identical discoveries."""
    lock_goal(sess, goals, source_data["goal_id"])
    if reuse:
        rows = sess.execute(
            select(table).where(
                table.c.goal_id == source_data["goal_id"], table.c.reference == source_data["reference"]
            )
        ).all()
        for row in rows:
            existing = dict(row._mapping)
            config = {key: value for key, value in (existing.get("config") or {}).items() if key != "metadata"}
            requested = {key: value for key, value in (source_data.get("config") or {}).items() if key != "metadata"}
            if (
                existing.get("deleted_at") is not None
                or existing["type"] != source_data["type"]
                or existing.get("credential_ref") != source_data.get("credential_ref")
                or config != requested
            ):
                raise ValueError(
                    "Source "
                    + existing["id"]
                    + " already uses this reference with conflicting configuration or is archived"
                )
        if rows:
            return dict(rows[0]._mapping)
    return dict(sess.execute(table.insert().values(**source_data).returning(table)).one()._mapping)


def link_goal_routine(sess: Any, goals: Any, goal_id: str, schedule_id: str) -> Dict[str, Any]:
    """Serialize metadata appends without comparing database-specific JSON encodings."""
    from agno.db.schemas.goals import goal_metadata

    lock_goal(sess, goals, goal_id)
    row = sess.execute(select(goals).where(goals.c.id == goal_id)).one()
    metadata = goal_metadata(dict(row._mapping["metadata"] or {}))
    ids = list(metadata.get("routine_ids") or [])
    if schedule_id not in ids:
        metadata["routine_ids"] = [*ids, schedule_id]
        row = sess.execute(
            goals.update()
            .where(goals.c.id == goal_id)
            .values(metadata=metadata, updated_at=int(time.time()))
            .returning(goals)
        ).one()
    return dict(row._mapping)


def update_goal_row(
    sess: Any, goals: Any, goal_id: str, user_id: Optional[str], fields: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Update an active Goal; replacing metadata keeps the Routine ids linked to it."""
    stmt = goals.update().where(goals.c.id == goal_id, goals.c.deleted_at.is_(None))
    if user_id is not None:
        stmt = stmt.where(goals.c.user_id == user_id)
    if "metadata" in fields and "routine_ids" not in fields["metadata"]:
        # A no-op UPDATE takes the write lock link_goal_routine uses before reading the links.
        row = sess.execute(stmt.values(updated_at=goals.c.updated_at).returning(goals.c.metadata)).first()
        if row is None:
            return None
        routine_ids = (row[0] or {}).get("routine_ids")
        if routine_ids:
            fields = {**fields, "metadata": {**fields["metadata"], "routine_ids": routine_ids}}
    result = sess.execute(stmt.values(**fields, updated_at=int(time.time())).returning(goals)).fetchone()
    return dict(result._mapping) if result else None


def initialize_company_details(sess: Any, table: Any, name: str, description: Optional[str]) -> Dict[str, Any]:
    """Keep one row: configuration fills or updates it until a human edits it, then never overwrites.

    An edit always moves updated_at past created_at, so equal timestamps mean never edited.
    """
    validate_company_details({"name": name, "description": description})
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if sess.bind.dialect.name == "postgresql" else sqlite_insert
    now = int(time.time())
    sess.execute(
        insert(table)
        .values(id="company", name=name, description=description, created_at=now, updated_at=now)
        .on_conflict_do_nothing(index_elements=[table.c.id])
    )
    current = sess.execute(select(table).where(table.c.id == "company")).one()._mapping
    if current["created_at"] != current["updated_at"] or (current["name"], current["description"]) == (
        name,
        description,
    ):
        return dict(current)
    # Moves both timestamps: they stay equal, and a client holding the old version gets a conflict.
    stamp = max(now, current["updated_at"] + 1)
    sess.execute(
        table.update()
        .where(
            table.c.id == "company",
            table.c.created_at == current["created_at"],
            table.c.updated_at == current["updated_at"],
        )
        .values(name=name, description=description, created_at=stamp, updated_at=stamp)
    )
    return dict(sess.execute(select(table).where(table.c.id == "company")).one()._mapping)


def update_company_details(
    sess: Any, table: Any, expected_updated_at: int, fields: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Reject stale edits atomically, including two edits made within one second."""
    validate_company_details(fields)
    if not fields:
        row = sess.execute(
            select(table).where(table.c.id == "company", table.c.updated_at == expected_updated_at)
        ).first()
    else:
        row = sess.execute(
            table.update()
            .where(table.c.id == "company", table.c.updated_at == expected_updated_at)
            .values(**fields, updated_at=max(int(time.time()), expected_updated_at + 1))
            .returning(table)
        ).first()
    return dict(row._mapping) if row is not None else None
