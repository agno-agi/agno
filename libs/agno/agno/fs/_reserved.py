"""Namespaces that belong to a part of Agno, which an agent's own filesystem must not open.

A file table is taken for the reserved one unless it is known to be another: a guard that lets an
unknown database through does not guard.
"""

import os
from typing import Any, NamedTuple, Optional, Set, Tuple
from weakref import WeakKeyDictionary

from agno.fs._place import database_place, is_private


class _Reserved(NamedTuple):
    dialect: str
    # Where the database is, or None when that is not known.
    place: Optional[tuple]
    schema: Optional[str]
    table: str
    namespace: str


_reserved: Set[_Reserved] = set()
# A database in memory is reserved for its own engine.
_by_engine: "WeakKeyDictionary[Any, Set[Tuple[str, str]]]" = WeakKeyDictionary()


def reserve_namespace(backend: Any, namespace: str) -> None:
    """Keep the shared partition of a namespace of this file table for its owner."""
    engine = backend.db_engine
    if is_private(engine):
        _by_engine.setdefault(engine, set()).add((backend.table_name, namespace))
        return
    _reserved.add(_Reserved(backend.dialect, database_place(engine), backend.db_schema, backend.table_name, namespace))


def _same_database(one: Optional[tuple], other: Optional[tuple]) -> bool:
    """Whether two places can be one database. Only what is known to differ is another database."""
    if one is None or other is None or one == other:
        return True
    if one[0] != "sqlite":
        # One server has many names, so a different host or port does not make another database.
        return one[-1] == other[-1]
    try:
        # A hard link, or another case on a file system that ignores it, names the same file.
        return os.path.samefile(one[1], other[1])
    except OSError:
        return False


def is_reserved(backend: Any, namespace: str) -> bool:
    """Whether the namespace of this file table belongs to a part of Agno that is not this backend."""
    engine = getattr(backend, "db_engine", None)
    if engine is None or getattr(backend, "owns_reserved_namespace", False):
        return False
    if is_private(engine):
        return (backend.table_name, namespace) in _by_engine.get(engine, ())
    candidates = [
        entry
        for entry in _reserved
        if (entry.dialect, entry.table, entry.namespace) == (backend.dialect, backend.table_name, namespace)
        # With no schema named, the search_path chooses it.
        and (entry.schema == backend.db_schema or None in (entry.schema, backend.db_schema))
    ]
    return bool(candidates) and any(_same_database(entry.place, database_place(engine)) for entry in candidates)
