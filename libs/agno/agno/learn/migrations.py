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
contaminated legacy row that receives a write before the migration runs is
carried into the owner's user-scoped row, the other user's recorded user_id and
all. That post-upgrade shape is reported under "contaminated_keyed" and is
report-only -- by then the row holds the owner's own data too.

Contamination is detected by comparing the content's recorded user against the
row's owner column, and one backend cannot support that comparison: MongoDB's
upsert $sets the whole document, the user_id field included, so a collided row
there has its owner overwritten by the last writer and stays self-consistent.
On Mongo, contaminated=0 means the evidence is structurally unavailable, not
that no cross-user collision happened.

    from agno.learn.migrations import rekey_user_entity_learnings

    report = rekey_user_entity_learnings(db, dry_run=True)   # inspect first
    report = rekey_user_entity_learnings(db, dry_run=False)  # then apply

Only deployments that set namespace="user" on entity memory are affected; the
default "global" namespace and custom namespaces keep their keys unchanged.
"""

from typing import Any, Dict, List, Tuple, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.learn.utils import _parse_json, build_learning_id, legacy_entity_learning_id
from agno.utils.log import log_info, log_warning

_ENTITY_LEARNING_TYPE = "entity_memory"
_PAGE_SIZE = 500

# Buckets the migration only reports on, and the subset purge_unrecoverable deletes.
_REPORT_ONLY = ("contaminated", "contaminated_keyed", "unowned", "malformed")
_PURGEABLE = ("contaminated", "unowned")


def _classify_row(row: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Sort a namespace="user" entity row into a migration bucket.

    Returns the bucket and the row's parsed content. Only "legacy" rows are
    re-keyed, and only they carry a content dict here; every other bucket
    returns an empty dict, since nothing is written from it.

    - "keyed": already on a user-scoped key, nothing to do.
    - "malformed": missing the entity identity columns, so no key can be derived,
      or content that does not parse to a dict, so ownership cannot be checked.
    - "unowned": no user_id column; unreachable by any user-filtered read.
    - "contaminated": the content's recorded user differs from the row's owner,
      so more than one user has written it and the earlier data is gone.
    - "contaminated_keyed": that same disagreement on an already user-scoped row.
      The owner's first post-upgrade write merges a contaminated legacy row into
      their new row and carries the other user's recorded user_id along, so the
      row holds the owner's own data as well and is only ever reported.
    """
    entity_id = row.get("entity_id")
    entity_type = row.get("entity_type")
    if not (entity_id and entity_type):
        return "malformed", {}
    content = _parse_json(row.get("content"))
    if not isinstance(content, dict):
        return "malformed", {}
    owner = row.get("user_id")
    content_user = content.get("user_id")
    contaminated = bool(owner) and content_user is not None and content_user != owner
    if row.get("learning_id") != legacy_entity_learning_id(entity_id, entity_type, "user"):
        return ("contaminated_keyed" if contaminated else "keyed"), {}
    if not owner:
        return "unowned", {}
    if contaminated:
        return "contaminated", {}
    return "legacy", content


def _new_id_for(row: Dict[str, Any]) -> str:
    """The user-scoped key for a row the classifier put in the "legacy" bucket.

    That bucket guarantees entity_id, entity_type and user_id are all present,
    which is exactly what build_learning_id needs to return an id.
    """
    return cast(
        str,
        build_learning_id(
            _ENTITY_LEARNING_TYPE,
            user_id=row.get("user_id"),
            entity_id=row.get("entity_id"),
            entity_type=row.get("entity_type"),
            namespace="user",
        ),
    )


def _delete_confirmed(db: BaseDb, learning_id: str) -> bool:
    """Whether the row is gone once the db has been asked to delete it.

    Every adapter's delete_learning swallows its exception and returns False, so
    False alone cannot tell a failed delete from a row a concurrent writer had
    already removed; the read-back separates the two.
    """
    if db.delete_learning(id=learning_id):
        return True
    return db.get_learning_by_id(learning_id) is None


async def _adelete_confirmed(db: AsyncBaseDb, learning_id: str) -> bool:
    """Async version of _delete_confirmed."""
    if await db.delete_learning(id=learning_id):
        return True
    return await db.get_learning_by_id(learning_id) is None


def _report(buckets: Dict[str, List[str]], scanned: int, keyed: int, dry_run: bool) -> Dict[str, Any]:
    report: Dict[str, Any] = {"scanned": scanned, "keyed": keyed, "dry_run": dry_run, **buckets}
    counts = " ".join(f"{name}={len(ids)}" for name, ids in buckets.items())
    log_info(f"rekey_user_entity_learnings: scanned={scanned} keyed={keyed} {counts} dry_run={dry_run}")
    return report


def _new_buckets() -> Dict[str, List[str]]:
    return {
        "rekeyed": [],
        "contaminated": [],
        "contaminated_keyed": [],
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
    intact). delete_learning swallows failures the same way, so its result is
    confirmed by a read-back too: a source row that survives its own delete leaves
    a duplicate behind and is reported as "failed", never as "rekeyed". Re-keyed
    rows restart created_at and updated_at at migration time -- the upsert surface
    carries no timestamps -- so entity recency ordering resets; the content keeps
    its original timestamps.

    Every namespace="user" entity row is paged into memory before anything is
    written: deleting rows while paging the same table shifts the LIMIT/OFFSET
    window and skips rows. Peak memory therefore scales with that row count.

    Rows are never merged: a row whose target key already exists is reported
    under "conflicts" and left in place. The store's write path folds such a row
    into the user-scoped row on the owner's next write -- a deterministic gated
    merge that retires the legacy row only once its content is carried across, so
    convergence drops nothing -- and a conflict therefore either clears itself
    that way or keeps being reported here.

    A row that raises while it is processed is reported under "failed" and the
    walk continues, so the report always accounts for every scanned row.

    Args:
        db: The database whose learnings table to migrate.
        dry_run: When True (the default), report what would change without writing.
        purge_unrecoverable: When True, delete every row reported as contaminated
            or unowned instead of leaving it. Contaminated rows hold one user's
            facts under another user's ownership and cannot be split; unowned rows
            are unreachable by any user-filtered read. Deployments with a strict
            privacy posture should purge and let entity memory re-capture from
            conversation. Malformed and contaminated_keyed rows are never deleted:
            a contaminated_keyed row also carries its owner's own post-upgrade
            writes, so deleting it would destroy recoverable data.

    Returns:
        A report dict: "scanned", "keyed" (a count, not a list -- rows already on
        a user-scoped key are usually the bulk of the table), "dry_run", and
        per-bucket lists of learning ids: rekeyed, contaminated,
        contaminated_keyed, unowned, malformed, conflicts, failed, purged. Each
        scanned row is counted once across "keyed" and the id buckets, so they
        reconcile with "scanned"; "purged" repeats ids already listed under
        contaminated or unowned, and a purge whose delete cannot be confirmed adds
        that id to "failed" too.
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
    keyed = 0
    for row in rows:
        old_id = row.get("learning_id", "")
        try:
            bucket, content = _classify_row(row)
            if bucket == "keyed":
                keyed += 1
                continue
            if bucket in _REPORT_ONLY:
                buckets[bucket].append(old_id)
                if purge_unrecoverable and bucket in _PURGEABLE:
                    if dry_run or _delete_confirmed(db, old_id):
                        buckets["purged"].append(old_id)
                    else:
                        log_warning(f"rekey_user_entity_learnings: could not purge {old_id}; the row is still there")
                        buckets["failed"].append(old_id)
                continue

            new_id = _new_id_for(row)
            if db.get_learning_by_id(new_id) is not None:
                buckets["conflicts"].append(old_id)
                continue
            if dry_run:
                buckets["rekeyed"].append(old_id)
                continue
            db.upsert_learning(
                id=new_id,
                learning_type=_ENTITY_LEARNING_TYPE,
                content=content,
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
            if _delete_confirmed(db, old_id):
                buckets["rekeyed"].append(old_id)
            else:
                log_warning(
                    f"rekey_user_entity_learnings: copied {old_id} to {new_id} but could not delete the source row; "
                    "both rows now exist"
                )
                buckets["failed"].append(old_id)
        except Exception as e:
            log_warning(f"rekey_user_entity_learnings: skipping {old_id}: {e}")
            buckets["failed"].append(old_id)

    return _report(buckets, len(rows), keyed, dry_run)


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
    keyed = 0
    for row in rows:
        old_id = row.get("learning_id", "")
        try:
            bucket, content = _classify_row(row)
            if bucket == "keyed":
                keyed += 1
                continue
            if bucket in _REPORT_ONLY:
                buckets[bucket].append(old_id)
                if purge_unrecoverable and bucket in _PURGEABLE:
                    if dry_run or await _adelete_confirmed(db, old_id):
                        buckets["purged"].append(old_id)
                    else:
                        log_warning(f"rekey_user_entity_learnings: could not purge {old_id}; the row is still there")
                        buckets["failed"].append(old_id)
                continue

            new_id = _new_id_for(row)
            if await db.get_learning_by_id(new_id) is not None:
                buckets["conflicts"].append(old_id)
                continue
            if dry_run:
                buckets["rekeyed"].append(old_id)
                continue
            await db.upsert_learning(
                id=new_id,
                learning_type=_ENTITY_LEARNING_TYPE,
                content=content,
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
            if await _adelete_confirmed(db, old_id):
                buckets["rekeyed"].append(old_id)
            else:
                log_warning(
                    f"rekey_user_entity_learnings: copied {old_id} to {new_id} but could not delete the source row; "
                    "both rows now exist"
                )
                buckets["failed"].append(old_id)
        except Exception as e:
            log_warning(f"rekey_user_entity_learnings: skipping {old_id}: {e}")
            buckets["failed"].append(old_id)

    return _report(buckets, len(rows), keyed, dry_run)
