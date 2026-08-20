"""Turning an ``offload_tool_results`` setting into the ResultStore a run uses."""

from __future__ import annotations

from typing import Any, Optional, Set, Tuple, Union

from agno.offload.store import ResultStore
from agno.utils.log import log_warning

# Payloads go to AgentFS, whose database backend is sync, and the index table
# agno_tool_results is implemented by SqliteDb and PostgresDb. Anywhere else
# the setting is honoured as off, with one warning: a run must never believe
# its payloads are recoverable when they are not.
_OFFLOAD_SUPPORTED_DBS = ("SqliteDb", "PostgresDb")

# Warnings already emitted, keyed by owner and reason. AgentOS runs a fresh
# copy of an agent per request, so the key outlives any one instance.
_WARNED: Set[Tuple[Any, str]] = set()


def _warn_once(owner: Any, reason: str) -> None:
    key = (getattr(owner, "id", None) or getattr(owner, "name", None) or id(owner), reason)
    if key not in _WARNED:
        _WARNED.add(key)
        log_warning(reason)


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
            "offload_tool_results must be True, False or a ResultStore; "
            "set the threshold with ResultStore(threshold_chars=...)."
        )

    if store.db is None:
        _warn_once(owner, f"offload_tool_results needs a db; offloading is off for this {owner_kind}.")
        return None

    backend_name = type(store.db).__name__
    if backend_name not in _OFFLOAD_SUPPORTED_DBS:
        _warn_once(
            owner,
            f"Result offloading is not available on {backend_name}; offloading is off for this {owner_kind}. "
            "It needs SqliteDb or PostgresDb, because stored payloads go through the sync filesystem backend.",
        )
        return None

    try:
        store.fs
    except Exception as e:
        _warn_once(owner, f"Result offloading could not reach the filesystem backend ({e}); offloading is off.")
        return None

    return store


__all__ = ["build_result_store"]
