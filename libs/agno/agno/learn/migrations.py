"""
Learning Store Migrations
=========================
One-off data migrations for the learning stores.

rekey_user_entity_learnings: entity_memory rows written under namespace="user"
before the row key embedded the user carry a user-less key, so same-named
entities collided across users. This helper re-keys each surviving row to its
recorded owner's user-scoped key. Rows that provably held more than one user's
data (the content's recorded user differs from the row's owner column) are
reported, not silently re-keyed -- their original data is not separable.

Run it once per database, before the upgraded application serves writes: the
store's write path merges whatever the column-filtered read returns, so a
contaminated row that receives a write before the migration runs is no longer
detectable as contaminated.

    from agno.learn.migrations import rekey_user_entity_learnings

    report = rekey_user_entity_learnings(db, dry_run=True)   # inspect first
    report = rekey_user_entity_learnings(db, dry_run=False)  # then apply

Only deployments that set namespace="user" on entity memory are affected; the
default "global" namespace and custom namespaces keep their keys unchanged.
"""

from typing import Any, Dict, List

from agno.db.base import AsyncBaseDb, BaseDb
from agno.learn.utils import _parse_json, build_learning_id, legacy_entity_learning_id
from agno.utils.log import log_info

_ENTITY_LEARNING_TYPE = "entity_memory"
_PAGE_SIZE = 500


def _classify_row(row: Dict[str, Any]) -> str:
    """Sort a namespace="user" entity row into a migration bucket.

    "legacy" rows are re-keyable; every other bucket needs the operator:
    - "keyed": already on a user-scoped key, nothing to do.
    - "malformed": missing the entity identity columns, so no key can be derived.
    - "unowned": no user_id column; unreachable by any user-filtered read.
    - "contaminated": the content's recorded user differs from the row's owner,
      so more than one user has written it and the earlier data is gone.
    """
    entity_id = row.get("entity_id")
    entity_type = row.get("entity_type")
    if not (entity_id and entity_type):
        return "malformed"
    if row.get("learning_id") != legacy_entity_learning_id(entity_id, entity_type, "user"):
        return "keyed"
    owner = row.get("user_id")
    if not owner:
        return "unowned"
    content = _parse_json(row.get("content")) or {}
    content_user = content.get("user_id")
    if content_user is not None and content_user != owner:
        return "contaminated"
    return "legacy"


def _report(buckets: Dict[str, List[str]], scanned: int, dry_run: bool) -> Dict[str, Any]:
    report: Dict[str, Any] = {"scanned": scanned, "dry_run": dry_run, **buckets}
    counts = " ".join(f"{name}={len(ids)}" for name, ids in buckets.items())
    log_info(f"rekey_user_entity_learnings: scanned={scanned} {counts} dry_run={dry_run}")
    return report


def _new_buckets() -> Dict[str, List[str]]:
    return {
        "rekeyed": [],
        "contaminated": [],
        "unowned": [],
        "malformed": [],
        "conflicts": [],
        "failed": [],
        "purged": [],
    }


def rekey_user_entity_learnings(
    db: BaseDb,
    *,
    dry_run: bool = True,
    purge_unrecoverable: bool = False,
) -> Dict[str, Any]:
    """Re-key namespace="user" entity_memory rows to their owner's user-scoped key.

    For each legacy-keyed row the new key is derived from the row's own user_id
    column, the content is carried over unchanged, and the old row is deleted only
    after the re-keyed row is read back (the adapters' upsert_learning swallows
    failures; a failed write lands in the "failed" bucket with the source row
    intact). Re-keyed rows restart created_at and updated_at at migration time --
    the upsert surface carries no timestamps -- so entity recency ordering resets;
    the content keeps its original timestamps.

    Rows are never merged: a row whose target key already exists is reported
    under "conflicts" and left in place. The store's write path retires such a
    row only once its content is fully carried by the user-scoped row, so a
    conflict either resolves itself on the owner's next write or keeps being
    reported here.

    Args:
        db: The database whose learnings table to migrate.
        dry_run: When True (the default), report what would change without writing.
        purge_unrecoverable: When True, delete the rows reported as contaminated
            or unowned instead of leaving them. Contaminated rows hold one user's
            facts under another user's ownership and cannot be split; unowned rows
            are unreachable by any user-filtered read. Deployments with a strict
            privacy posture should purge and let entity memory re-capture from
            conversation. Malformed rows are only ever reported.

    Returns:
        A report dict: scanned count, dry_run, and per-bucket lists of learning
        ids (rekeyed, contaminated, unowned, malformed, conflicts, failed, purged).
    """
    rows: List[Dict[str, Any]] = []
    page = 1
    while True:
        batch, total = db.list_learnings(
            learning_type=_ENTITY_LEARNING_TYPE,
            namespace="user",
            limit=_PAGE_SIZE,
            page=page,
            # updated_at (the default sort) is second-resolution and ties across a
            # bulk write, which makes LIMIT/OFFSET pages overlap; the unique key
            # makes the walk deterministic.
            sort_by="learning_id",
            sort_order="asc",
        )
        rows.extend(batch or [])
        if not batch or len(rows) >= total:
            break
        page += 1

    buckets = _new_buckets()
    for row in rows:
        old_id = row.get("learning_id", "")
        bucket = _classify_row(row)
        if bucket == "keyed":
            continue
        if bucket in ("unowned", "contaminated", "malformed"):
            buckets[bucket].append(old_id)
            if purge_unrecoverable and bucket != "malformed":
                buckets["purged"].append(old_id)
                if not dry_run:
                    db.delete_learning(id=old_id)
            continue

        new_id = build_learning_id(
            _ENTITY_LEARNING_TYPE,
            user_id=row.get("user_id"),
            entity_id=row.get("entity_id"),
            entity_type=row.get("entity_type"),
            namespace="user",
        )
        if new_id is None:
            buckets["unowned"].append(old_id)
            continue
        if db.get_learning_by_id(new_id) is not None:
            buckets["conflicts"].append(old_id)
            continue
        if dry_run:
            buckets["rekeyed"].append(old_id)
            continue
        db.upsert_learning(
            id=new_id,
            learning_type=_ENTITY_LEARNING_TYPE,
            content=_parse_json(row.get("content")) or {},
            user_id=row.get("user_id"),
            agent_id=row.get("agent_id"),
            team_id=row.get("team_id"),
            session_id=row.get("session_id"),
            namespace="user",
            entity_id=row.get("entity_id"),
            entity_type=row.get("entity_type"),
            metadata=_parse_json(row.get("metadata")),
        )
        if db.get_learning_by_id(new_id) is None:
            buckets["failed"].append(old_id)
            continue
        buckets["rekeyed"].append(old_id)
        db.delete_learning(id=old_id)

    return _report(buckets, len(rows), dry_run)


async def arekey_user_entity_learnings(
    db: AsyncBaseDb,
    *,
    dry_run: bool = True,
    purge_unrecoverable: bool = False,
) -> Dict[str, Any]:
    """Async version of rekey_user_entity_learnings."""
    rows: List[Dict[str, Any]] = []
    page = 1
    while True:
        batch, total = await db.list_learnings(
            learning_type=_ENTITY_LEARNING_TYPE,
            namespace="user",
            limit=_PAGE_SIZE,
            page=page,
            sort_by="learning_id",
            sort_order="asc",
        )
        rows.extend(batch or [])
        if not batch or len(rows) >= total:
            break
        page += 1

    buckets = _new_buckets()
    for row in rows:
        old_id = row.get("learning_id", "")
        bucket = _classify_row(row)
        if bucket == "keyed":
            continue
        if bucket in ("unowned", "contaminated", "malformed"):
            buckets[bucket].append(old_id)
            if purge_unrecoverable and bucket != "malformed":
                buckets["purged"].append(old_id)
                if not dry_run:
                    await db.delete_learning(id=old_id)
            continue

        new_id = build_learning_id(
            _ENTITY_LEARNING_TYPE,
            user_id=row.get("user_id"),
            entity_id=row.get("entity_id"),
            entity_type=row.get("entity_type"),
            namespace="user",
        )
        if new_id is None:
            buckets["unowned"].append(old_id)
            continue
        if await db.get_learning_by_id(new_id) is not None:
            buckets["conflicts"].append(old_id)
            continue
        if dry_run:
            buckets["rekeyed"].append(old_id)
            continue
        await db.upsert_learning(
            id=new_id,
            learning_type=_ENTITY_LEARNING_TYPE,
            content=_parse_json(row.get("content")) or {},
            user_id=row.get("user_id"),
            agent_id=row.get("agent_id"),
            team_id=row.get("team_id"),
            session_id=row.get("session_id"),
            namespace="user",
            entity_id=row.get("entity_id"),
            entity_type=row.get("entity_type"),
            metadata=_parse_json(row.get("metadata")),
        )
        if await db.get_learning_by_id(new_id) is None:
            buckets["failed"].append(old_id)
            continue
        buckets["rekeyed"].append(old_id)
        await db.delete_learning(id=old_id)

    return _report(buckets, len(rows), dry_run)
