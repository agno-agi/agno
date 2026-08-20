"""Migration v3.0.0: re-key namespace="user" entity_memory learnings

Changes:
- entity_memory rows written under namespace="user" carry a key with no user
  component, so two users recording the same entity name and type shared one
  row. Each surviving row is re-keyed to its recorded owner's user-scoped key.

Rows that provably held more than one user's data are reported and left in
place: their original content is not separable, and deleting them is a choice
for the operator to make with agno.learn.migrations.rekey_user_entity_learnings
and purge_unrecoverable=True.
"""

from typing import Any, Dict, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.utils.log import log_error, log_info, log_warning

_TABLE_TYPE = "learnings"


def _report_outcome(report: Dict[str, Any], table_name: str) -> bool:
    """Log what the re-key did and whether anything needs an operator.

    Returns True when at least one row moved, which is what marks the migration
    as applied.
    """
    rekeyed = len(report.get("rekeyed") or [])
    log_info(f"Re-keyed {rekeyed} namespace='user' entity_memory row(s) on table {table_name}")

    for bucket, note in (
        ("contaminated", "hold more than one user's data and were left in place"),
        ("contaminated_keyed", "record a user other than their owner and were left in place"),
        ("unowned", "have no owner and are unreachable by any user-filtered read"),
        ("malformed", "are missing the entity columns or do not parse"),
        ("conflicts", "already have a row on the target key"),
        ("failed", "could not be moved"),
    ):
        ids = report.get(bucket) or []
        if ids:
            log_warning(
                f"{len(ids)} entity_memory row(s) on table {table_name} {note}: {', '.join(ids[:10])}"
                f"{' and more' if len(ids) > 10 else ''}. "
                "See agno.learn.migrations.rekey_user_entity_learnings to resolve them."
            )

    return rekeyed > 0


def _unsupported(db: Union[BaseDb, AsyncBaseDb]) -> bool:
    """Whether this backend stores learnings at all."""
    return not hasattr(db, "list_learnings")


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Re-key namespace="user" entity_memory rows to their owner's key."""
    if table_type != _TABLE_TYPE:
        return False

    from agno.learn.migrations import rekey_user_entity_learnings

    db_type = type(db).__name__
    try:
        if _unsupported(db):
            log_info(f"{db_type} does not store learnings")
            return False
        report = rekey_user_entity_learnings(db, dry_run=False)
    except NotImplementedError:
        log_info(f"{db_type} does not store learnings")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise

    return _report_outcome(report, table_name)


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async version of up."""
    if table_type != _TABLE_TYPE:
        return False

    from agno.learn.migrations import arekey_user_entity_learnings

    db_type = type(db).__name__
    try:
        if _unsupported(db):
            log_info(f"{db_type} does not store learnings")
            return False
        report = await arekey_user_entity_learnings(db, dry_run=False)
    except NotImplementedError:
        log_info(f"{db_type} does not store learnings")
        return False
    except Exception as e:
        log_error(f"Error running migration v3.0.0 for {db_type} on table {table_name}: {str(e)}")
        raise

    return _report_outcome(report, table_name)


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """The re-key has no reverse.

    The user-less key is shared by every user, so moving these rows back onto it
    recreates the collision this migration exists to undo.
    """
    if table_type != _TABLE_TYPE:
        return False
    log_warning(
        f"Migration v3.0.0 on table {table_name} cannot be reverted: the pre-3.0 entity_memory key "
        "is shared across users, so restoring it would collide the rows again"
    )
    return False


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async version of down."""
    return down(db, table_type, table_name)  # type: ignore[arg-type]
