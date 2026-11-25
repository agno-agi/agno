import os
from collections import Counter
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, unquote

if TYPE_CHECKING:
    from agno.fs import FileSystem

# Never part of a namespace, so an id that carries a backend cannot be read as another namespace.
_ID_SEPARATOR = ":"
# Marks a place known only as the engine itself, which no other process can name.
_ENGINE_PLACE = "engine"


def _connect_arguments(engine: Any) -> Optional[Tuple[tuple, Dict[str, Any]]]:
    """What the driver is called with: the URL, its query and ``connect_args``, or None when that is not known."""
    dialect = engine.dialect
    if getattr(dialect, "_has_events", False) and list(dialect.dispatch.do_connect):
        # A listener may connect anywhere.
        return None
    # SQLAlchemy has no public accessor for these. A custom creator or pool does not hold them.
    creator = getattr(engine.pool, "_creator", None)
    names = getattr(getattr(creator, "__code__", None), "co_freevars", ())
    held = {name: cell.cell_contents for name, cell in zip(names, getattr(creator, "__closure__", None) or ())}
    if held.get("dialect") is not dialect or "cargs_tup" not in held or "cparams" not in held:
        return None
    return tuple(held["cargs_tup"]), dict(held["cparams"])


def _sqlite_place(filename: Any, is_uri: bool) -> Optional[tuple]:
    """The file a SQLite connection opens, or None for a database that belongs to its engine."""
    path = str(filename or "")
    if is_uri and path.startswith("file:"):
        path, _, query = path[len("file:") :].partition("?")
        # Named and shared memory databases are kept apart too: listing one twice hides no file.
        if any(option in parse_qs(query) for option in ("mode", "cache", "vfs")):
            return None
        path = unquote(path[2:] if path.startswith("///") else path)
    if not path or path == ":memory:":
        return None
    return ("sqlite", str(Path(path).resolve()))


def _postgres_place(params: Dict[str, Any]) -> Optional[tuple]:
    """The server and database a PostgreSQL connection opens, or None when the driver chooses them."""
    if any(params.get(name) for name in ("service", "conninfo", "dsn")):
        return None
    # libpq applies these to a connection that names its own host.
    if os.getenv("PGSERVICE") or os.getenv("PGHOSTADDR"):
        return None
    host = params.get("hostaddr") or params.get("host")
    database = params.get("dbname") or params.get("database")
    # libpq reads a dbname that is itself a connection string.
    if not host or not database or "=" in str(database) or "://" in str(database):
        return None
    port = params.get("port") or os.getenv("PGPORT") or "5432"
    return ("postgresql", str(host), str(port), str(database))


def _database_place(engine: Any) -> tuple:
    """The database an engine connects to: the same for every engine on it, synchronous or not.

    An engine whose database is not known for certain is its own place: listing
    one store twice hides no file, and merging two stores does.
    """
    arguments = _connect_arguments(engine)
    place: Optional[tuple] = None
    if arguments is not None:
        positional, params = arguments
        backend_name = engine.url.get_backend_name()
        if backend_name == "sqlite" and positional:
            place = _sqlite_place(positional[0], bool(params.get("uri")))
        elif backend_name == "postgresql" and not positional:
            place = _postgres_place(params)
    return place or (_ENGINE_PLACE, id(engine))


def _filesystem_backend_key(filesystem: "FileSystem") -> tuple:
    """Identify a shared backend within the current process.

    A table in a database is one backend however it is reached: through a
    database object, through an engine, or through two of either.
    """
    backend = filesystem.backend
    engine = getattr(backend, "db_engine", None)
    table_name = getattr(backend, "table_name", None)
    if engine is not None and table_name is not None:
        db_schema = getattr(backend, "db_schema", None)
        place = _database_place(engine)
        if db_schema is None and place[0] == "postgresql":
            # The search_path chooses the table, and a connection can set it outside the URL.
            place = (_ENGINE_PLACE, id(engine))
        return ("db", place, db_schema, table_name)
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
    ``handbook:main-db:fs.agno_fs``. A table adds a digest of its database, so
    databases with the same names keep their ids in any order. A folder on disk
    is named by its last segment and a digest of its path. An id never carries
    a server path.
    """
    name = filesystem.namespace if namespace is None else namespace
    backend = filesystem.backend
    table_name = getattr(backend, "table_name", None)
    root = getattr(backend, "root", None)
    if table_name is not None:
        db = getattr(backend, "db", None)
        db_schema = getattr(backend, "db_schema", None)
        parts = [str(getattr(db, "id", None) or "db"), f"{db_schema}.{table_name}" if db_schema else str(table_name)]
        place = _filesystem_backend_key(filesystem)[1]
        if isinstance(place, tuple) and place[0] != _ENGINE_PLACE:
            parts.append(sha1(repr(place).encode("utf-8")).hexdigest()[:8])
    elif root is not None:
        parts = [Path(str(root)).name or "local", sha1(str(root).encode("utf-8")).hexdigest()[:8]]
    else:
        parts = [type(backend).__name__]
    forms = [name]
    for part in parts:
        forms.append(f"{forms[-1]}{_ID_SEPARATOR}{part}")
    return tuple(forms)


def _assign_filesystem_ids(
    forms_by_key: Dict[tuple, Tuple[str, ...]],
    reserved_forms: Iterable[Tuple[str, ...]] = (),
    reserved_ids: Iterable[str] = (),
    *,
    unnumbered_first: bool = True,
) -> Dict[tuple, str]:
    """Give each store its shortest form that names no other store, in ``forms_by_key`` or reserved.

    Stores whose backends have the same names share every form. They are numbered
    in order, skipping any number that would name another store. Without ``unnumbered_first``
    the first of them has a number too: the form alone is one the others answer to, so it would
    open another store when the first is not there.
    """
    reserved = {form for forms in reserved_forms for form in forms} | set(reserved_ids)
    counts = Counter(form for forms in forms_by_key.values() for form in forms)
    assigned: Dict[tuple, str] = {}
    taken = set(reserved)
    for key, forms in forms_by_key.items():
        chosen = next((form for form in forms if counts[form] == 1 and form not in reserved), None)
        if chosen is None:
            # A form another store takes as its own is not given, with or without a number.
            chosen, position = forms[-1], 1
            if not unnumbered_first:
                position = 1 if chosen in reserved else 0
            while chosen in taken or (chosen in counts and not (unnumbered_first and position == 1)):
                position += 1
                chosen = f"{forms[-1]}{_ID_SEPARATOR}{position}"
        taken.add(chosen)
        assigned[key] = chosen
    return assigned


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
    ids.update(_assign_filesystem_ids(held_forms, declared_forms.values(), list(ids.values()), unnumbered_first=False))
    return ids


def _can_share_every_name(key: tuple) -> bool:
    """Whether another store can have every name of this one, because where its files are is not known."""
    backend = key[0]
    if backend[0] == "backend":
        return True
    return backend[0] == "db" and not (isinstance(backend[1], tuple) and backend[1][0] != _ENGINE_PLACE)


def _match_filesystem_id(filesystem_id: str, candidates: List[Tuple[str, Tuple[str, ...]]]) -> List[int]:
    """Positions of the ``(id, forms)`` candidates a requested id names: its own id first, else any of its forms.

    A longer form keeps naming a store whose id is shorter, so an id taken while
    another store shared the namespace still resolves once that store is gone.
    """
    exact = [index for index, (candidate_id, _) in enumerate(candidates) if candidate_id == filesystem_id]
    if exact:
        return exact
    return [index for index, (_, forms) in enumerate(candidates) if filesystem_id in forms]
