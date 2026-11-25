"""Where a database is, so that two handles on one database are known to be one."""

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote


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


def database_place(engine: Any) -> Optional[tuple]:
    """The database a SQLAlchemy engine connects to: the same for every engine on it, synchronous or not.

    None when that is not known for certain, or when the database belongs to its engine.
    """
    engine = getattr(engine, "sync_engine", engine)
    arguments = _connect_arguments(engine)
    if arguments is None:
        return None
    positional, params = arguments
    backend_name = engine.url.get_backend_name()
    if backend_name == "sqlite" and positional:
        return _sqlite_place(positional[0], bool(params.get("uri")))
    if backend_name == "postgresql" and not positional:
        return _postgres_place(params)
    return None
