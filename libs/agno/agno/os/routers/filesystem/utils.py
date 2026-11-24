from collections import Counter
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from agno.fs import FileSystem

# Never part of a namespace, so an id that carries a backend cannot be read as another namespace.
_ID_SEPARATOR = ":"


def _filesystem_backend_key(filesystem: "FileSystem") -> tuple:
    """Identify a shared backend within the current process."""
    backend = filesystem.backend
    db = getattr(backend, "db", None)
    if db is not None:
        return (
            "db",
            getattr(db, "id", None) or id(db),
            getattr(backend, "db_schema", None),
            getattr(backend, "table_name", None),
        )
    root = getattr(backend, "root", None)
    if root is not None:
        return ("local", str(root))
    return ("backend", id(backend))


def _filesystem_key(filesystem: "FileSystem", namespace: Optional[str] = None) -> tuple:
    """Identify one store within the current process: its backend and its namespace."""
    return (_filesystem_backend_key(filesystem), filesystem.namespace if namespace is None else namespace)


def _filesystem_id_forms(filesystem: "FileSystem", namespace: Optional[str] = None) -> Tuple[str, ...]:
    """The ids that can name a filesystem, shortest first.

    The namespace, then the namespace with its backend, then with the table or
    folder inside that backend: ``handbook``, ``handbook:main-db``,
    ``handbook:main-db:fs.agno_fs``. A folder on disk is named by its last
    segment and a digest of its path, so an id never carries a server path.
    """
    name = filesystem.namespace if namespace is None else namespace
    backend = filesystem.backend
    table_name = getattr(backend, "table_name", None)
    root = getattr(backend, "root", None)
    if table_name is not None:
        db = getattr(backend, "db", None)
        db_schema = getattr(backend, "db_schema", None)
        parts = [str(getattr(db, "id", None) or "db"), f"{db_schema}.{table_name}" if db_schema else str(table_name)]
    elif root is not None:
        parts = [Path(str(root)).name or "local", sha1(str(root).encode("utf-8")).hexdigest()[:8]]
    else:
        parts = [type(backend).__name__]
    forms = [name]
    for part in parts:
        forms.append(f"{forms[-1]}{_ID_SEPARATOR}{part}")
    return tuple(forms)


def _assign_filesystem_ids(
    forms_by_key: Dict[tuple, Tuple[str, ...]], reserved: Iterable[Tuple[str, ...]] = ()
) -> Dict[tuple, str]:
    """Give each store its shortest form that names no other store, in ``forms_by_key`` or ``reserved``.

    Stores whose backends have the same names share every form. They are numbered
    in order, after the reserved ones.
    """
    reserved = list(reserved)
    counts = Counter(form for forms in [*reserved, *forms_by_key.values()] for form in forms)
    numbered = Counter(forms[-1] for forms in reserved)
    ids: Dict[tuple, str] = {}
    for key, forms in forms_by_key.items():
        chosen = next((form for form in forms if counts[form] == 1), None)
        if chosen is None:
            numbered[forms[-1]] += 1
            position = numbered[forms[-1]]
            chosen = forms[-1] if position == 1 else f"{forms[-1]}{_ID_SEPARATOR}{position}"
        ids[key] = chosen
    return ids


def _filesystem_ids(
    declared: Sequence[Tuple[tuple, Tuple[str, ...]]], held: Sequence[Tuple[tuple, Tuple[str, ...]]] = ()
) -> Dict[tuple, str]:
    """An id for each store, keyed as given: its namespace, with the backend added when two would share it.

    ``declared`` and ``held`` are ``(key, forms)`` pairs. The ids of declared
    stores depend on the declarations alone, so they stay the same whatever
    agents come and go. A store only agents hold takes the shortest form no
    declared store can be named by.
    """
    declared_forms: Dict[tuple, Tuple[str, ...]] = dict(declared)
    held_forms = {key: forms for key, forms in held if key not in declared_forms}
    ids = _assign_filesystem_ids(declared_forms)
    ids.update(_assign_filesystem_ids(held_forms, reserved=declared_forms.values()))
    return ids


def _match_filesystem_id(filesystem_id: str, candidates: List[Tuple[str, Tuple[str, ...]]]) -> List[int]:
    """Positions of the ``(id, forms)`` candidates a requested id names: its own id first, else any of its forms.

    A longer form keeps naming a store whose id is shorter, so an id taken while
    another store shared the namespace still resolves once that store is gone.
    """
    exact = [index for index, (candidate_id, _) in enumerate(candidates) if candidate_id == filesystem_id]
    if exact:
        return exact
    return [index for index, (_, forms) in enumerate(candidates) if filesystem_id in forms]
