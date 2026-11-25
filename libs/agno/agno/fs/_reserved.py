"""Namespaces that belong to a part of Agno, which an agent's own filesystem must not open."""

from typing import Any, Set, Tuple
from weakref import WeakKeyDictionary

from agno.fs._place import database_place

_by_place: Set[tuple] = set()
# An engine whose database is not known for certain is compared by itself.
_by_engine: "WeakKeyDictionary[Any, Set[tuple]]" = WeakKeyDictionary()


def _table(backend: Any, namespace: str) -> Tuple[Any, ...]:
    return (getattr(backend, "db_schema", None), getattr(backend, "table_name", None), namespace)


def reserve_namespace(backend: Any, namespace: str) -> None:
    """Keep the shared partition of a namespace of this file table for its owner."""
    engine = backend.db_engine
    place = database_place(engine)
    if place is not None:
        _by_place.add((place, *_table(backend, namespace)))
    _by_engine.setdefault(engine, set()).add(_table(backend, namespace))


def is_reserved(backend: Any, namespace: str) -> bool:
    """Whether the namespace of this file table belongs to a part of Agno that is not this backend."""
    engine = getattr(backend, "db_engine", None)
    if engine is None or getattr(backend, "owns_reserved_namespace", False):
        return False
    table = _table(backend, namespace)
    if table in _by_engine.get(engine, ()):
        return True
    if not any(entry[1:] == table for entry in _by_place):
        return False
    return (database_place(engine), *table) in _by_place
