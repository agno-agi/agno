"""Turning an ``offload_tool_results`` setting into the ResultStore a run uses."""

from __future__ import annotations

from typing import Any, Optional, Set, Tuple, Union

from agno.offload.store import ResultStore
from agno.utils.log import log_warning

# Warnings already emitted, keyed by owner and reason. AgentOS runs a fresh
# copy of an agent per request, so the key outlives any one instance. Bounded:
# a nameless owner gets a fresh random id per construction, and an unbounded
# set would grow for the life of the process on that path.
_WARNED: Set[Tuple[Any, str]] = set()
_MAX_WARNED_KEYS = 1024


def _warn_once(owner: Any, reason: str) -> None:
    key = (getattr(owner, "id", None) or getattr(owner, "name", None) or id(owner), reason)
    if key in _WARNED:
        return
    if len(_WARNED) < _MAX_WARNED_KEYS:
        _WARNED.add(key)
    log_warning(reason)


def _db_supports_offloading(db: Any) -> bool:
    """Whether this db can back a ResultStore.

    Payloads go to AgentFS, whose database backend is sync, and the index
    table agno_tool_results is implemented by SqliteDb and PostgresDb, so
    those classes and their subclasses qualify. Anywhere else the setting is
    honoured as off, with one warning: a run must never believe its payloads
    are recoverable when they are not.
    """
    supported: Tuple[type, ...] = ()
    # An instance of either class proves its module imports; a failed import
    # only rules that class out for this process.
    try:
        from agno.db.sqlite.sqlite import SqliteDb

        supported += (SqliteDb,)
    except ImportError:
        pass
    try:
        from agno.db.postgres.postgres import PostgresDb

        supported += (PostgresDb,)
    except ImportError:
        pass
    return isinstance(db, supported)


def build_result_store(
    *,
    setting: Union[bool, ResultStore, None],
    db: Optional[Any],
    owner: Any,
    owner_kind: str = "agent",
) -> Optional[ResultStore]:
    """The store this owner runs with, or None when offloading cannot run.

    ``setting`` is what the user passed as ``offload_tool_results``: True for
    the defaults, or a ``ResultStore`` carrying their settings. The setting
    itself is never modified; a ResultStore given by the user is bound to the
    owner's db as a copy. A None return means offloading is off for this
    owner, and nothing else may believe payloads are recoverable.
    """
    if setting is False or setting is None:
        return None
    if setting is True:
        store = ResultStore(db=db)
    elif isinstance(setting, ResultStore):
        store = setting.bound(db)
    else:
        raise TypeError(
            "offload_tool_results must be True, False, None or a ResultStore; "
            "set the threshold with ResultStore(threshold_chars=...)."
        )

    if store.db is None:
        _warn_once(owner, f"offload_tool_results needs a db; offloading is off for this {owner_kind}.")
        return None

    if not _db_supports_offloading(store.db):
        _warn_once(
            owner,
            f"Result offloading is not available on {type(store.db).__name__}; offloading is off for this "
            f"{owner_kind}. It needs SqliteDb or PostgresDb (or a subclass), because stored payloads go "
            "through the sync filesystem backend.",
        )
        return None

    try:
        fs = store.fs
    except Exception as e:
        _warn_once(owner, f"Result offloading could not reach the filesystem backend ({e}); offloading is off.")
        return None

    # The db's session delete removes payloads through every filesystem a
    # store on that db writes to, so a custom filesystem is cleaned up too.
    registered = getattr(store.db, "tool_result_filesystems", None)
    if registered is None:
        registered = []
        try:
            store.db.tool_result_filesystems = registered
        except Exception:
            registered = None
    if registered is not None:
        key = _storage_key(fs.backend)
        if all(_storage_key(existing.backend) != key for existing in registered):
            registered.append(fs)
    return store


def _storage_key(backend: Any) -> Tuple[Any, ...]:
    """What one filesystem backend writes to.

    Every store build wraps the db in a new backend object, so identity would
    register one entry per agent built. Two backends that write to the same
    engine, table and schema, or the same directory, are one entry.
    """
    engine = getattr(backend, "db_engine", None)
    return (
        type(backend).__name__,
        engine if engine is not None else id(backend),
        getattr(backend, "table_name", None),
        getattr(backend, "db_schema", None),
        str(getattr(backend, "root", "")),
    )


__all__ = ["build_result_store"]
