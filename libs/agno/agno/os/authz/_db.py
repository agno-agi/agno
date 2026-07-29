"""Resolving the database the authorization components persist to.

Authorization storage lives on the ``BaseDb`` contract (the ``*_authz_*`` methods in
:mod:`agno.db.base`, implemented by the sync SQLAlchemy backends and inherited as
``NotImplementedError`` everywhere else). These helpers are the only thing between a
user's ``db=`` / ``db_url=`` argument and that contract:

* :func:`db_from_url` turns a SQLAlchemy URL into the matching agno database, so
  ``ManagedRoleStore(db_url=...)`` keeps working without the caller having to build a
  ``SqliteDb`` or ``PostgresDb`` themselves.
* :func:`supports_authz` asks whether a database implements the contract by CALLING it
  rather than by inspecting it -- a backend that inherits the stubs raises
  ``NotImplementedError`` and answers False.

The previous version of this module reached past the contract entirely: it duck-typed
any object for a ``.db_engine`` and the authz components then built and queried their own
SQLAlchemy tables. That worked only by accident on backends nobody had tried (MySQL
raised a key-length error, the async backends raised ``AttributeError``) and ignored a
backend's configured schema and table-name overrides.
"""

from typing import Any, Optional

# Raised/shown when a managed-roles component is used without a usable database. Managed
# roles must be persisted: an in-memory store can't stay consistent across the multiple
# workers/replicas an AgentOS deployment runs, so a DB is required.
NO_DB_MESSAGE = (
    "ManagedRoleStore requires a SQL database — managed roles must be persisted, "
    "and an in-memory store cannot stay consistent across multiple workers/replicas. "
    "Pass db=/db_url= to the store, or hand it to AgentOS via "
    "AuthorizationConfig(role_store=...) together with a SQL db on AgentOS so the "
    "store adopts it."
)

# Shown when a database exists but cannot store authorization data.
UNSUPPORTED_DB_MESSAGE = (
    "{db_type} does not support authorization storage. The managed-roles tables are "
    "implemented by the SQL backends (SqliteDb, PostgresDb); pass one of those as db=, "
    "or a db_url= for the store to build one."
)


def db_from_url(db_url: str) -> Any:
    """Build the agno database matching ``db_url``.

    SQLite is configured for multi-threaded server use (``check_same_thread=False``) so a
    connection opened on one request thread can be reused on another -- the property
    AgentOS needs from any database it serves decisions from.
    """
    if db_url.startswith("sqlite"):
        import sqlalchemy as sa

        from agno.db.sqlite import SqliteDb

        return SqliteDb(db_engine=sa.create_engine(db_url, connect_args={"check_same_thread": False}))

    if db_url.startswith("postgres"):
        from agno.db.postgres import PostgresDb

        return PostgresDb(db_url=db_url)

    raise ValueError(
        f"Unsupported db_url for authorization storage: {db_url!r}. Authorization tables are "
        "implemented for SQLite and PostgreSQL; pass db= built from another agno backend if it "
        "implements the authz methods."
    )


def supports_authz(db: Any) -> bool:
    """Whether ``db`` implements the authorization contract.

    Determined by calling the cheapest read and seeing whether it raises
    ``NotImplementedError``, so a backend opts in by implementing the methods rather than
    by appearing on a list here. Any OTHER exception (a connection error, say) means the
    database is real and configured for authz but currently unreachable, which is not the
    same as unsupported.
    """
    if db is None:
        return False
    try:
        db.authz_name_is_role("__agno_authz_probe__")
    except NotImplementedError:
        return False
    except Exception:
        return True
    return True


def require_authz_db(db: Any) -> None:
    """Raise unless ``db`` can store authorization data."""
    if db is None:
        raise RuntimeError(NO_DB_MESSAGE)
    if not supports_authz(db):
        raise RuntimeError(UNSUPPORTED_DB_MESSAGE.format(db_type=type(db).__name__))


def resolve_authz_db(db: Optional[Any] = None, db_url: Optional[str] = None) -> Optional[Any]:
    """The database an authz component should use, from either constructor argument.

    ``db`` wins over ``db_url`` (the caller's explicit object). Returns None when neither
    is given, leaving the component unbound until AgentOS lends it the OS database.
    """
    if db is not None:
        return db
    if db_url:
        return db_from_url(db_url)
    return None
