"""SQLite / SQLCipher SQLAlchemy engine factories for :class:`SqliteDb` and :class:`AsyncSqliteDb`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

from agno.utils.log import log_debug

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine

try:
    from sqlalchemy import create_engine, event
    from sqlalchemy.ext.asyncio import create_async_engine
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

SQLCIPHER_EXTRA = "sqlite-encrypted"
SQLCIPHER_INSTALL_HINT = (
    f"SQLCipher support requires optional dependencies. "
    f"Install with: pip install agno[{SQLCIPHER_EXTRA}]"
)


def escape_sqlite_string_literal(value: str) -> str:
    """Escape a value for use inside a SQLite single-quoted string literal."""
    return value.replace("'", "''")


def resolve_passphrase(
    passphrase: Optional[str] = None,
    passphrase_env: Optional[str] = None,
) -> Tuple[Optional[str], bool]:
    """Resolve the database passphrase from arguments and/or environment.

    Returns:
        Tuple of (passphrase or None, encrypted flag).
    """
    if passphrase is not None and passphrase != "":
        return passphrase, True

    if passphrase_env:
        env_value = os.environ.get(passphrase_env)
        if env_value is None or env_value == "":
            raise ValueError(
                f"passphrase_env '{passphrase_env}' is set but the environment variable is missing or empty."
            )
        return env_value, True

    return None, False


def resolve_db_path(
    db_file: Optional[str],
    *,
    create_parent: bool = True,
) -> Tuple[Optional[str], Optional[Path]]:
    """Resolve and optionally create the parent directory for a database file."""
    if db_file is None:
        return None, None

    db_path = Path(db_file).resolve()
    if create_parent:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path), db_path


def _import_sqlcipher3():
    try:
        import sqlcipher3  # type: ignore[import-untyped]
    except ImportError as e:
        raise ImportError(SQLCIPHER_INSTALL_HINT) from e
    return sqlcipher3


def _import_aiosqlcipher():
    try:
        import aiosqlcipher  # type: ignore[import-untyped]
    except ImportError as e:
        raise ImportError(SQLCIPHER_INSTALL_HINT) from e
    return aiosqlcipher


def _apply_sqlcipher_pragma_sync(connection, passphrase: str) -> None:
    cursor = connection.cursor()
    cursor.execute(f"PRAGMA key = '{escape_sqlite_string_literal(passphrase)}'")
    cursor.close()


def _register_sqlcipher_pragma_listener(engine: Engine, passphrase: str) -> None:
    """Ensure every pooled sync connection sets the SQLCipher key."""

    @event.listens_for(engine, "connect")
    def _set_sqlcipher_key(dbapi_connection, connection_record) -> None:  # noqa: ARG001
        _apply_sqlcipher_pragma_sync(dbapi_connection, passphrase)


def create_sqlite_engine(
    *,
    db_file: Optional[str] = None,
    db_url: Optional[str] = None,
    passphrase: Optional[str] = None,
    passphrase_env: Optional[str] = None,
) -> Tuple["Engine", Optional[str], Optional[str], bool]:
    """Create a sync SQLAlchemy engine for SQLite or SQLCipher.

    Connection priority matches :class:`~agno.db.sqlite.sqlite.SqliteDb`:
    ``db_url`` if provided, else ``db_file``, else a default file in the cwd.

    Returns:
        Tuple of (engine, resolved db_file, resolved db_url, encrypted).
    """
    resolved_passphrase, encrypted = resolve_passphrase(passphrase, passphrase_env)

    if db_url is not None:
        if encrypted:
            raise ValueError(
                "Cannot combine SQLCipher passphrase with db_url. "
                "Use db_file with passphrase, or supply a pre-configured db_engine."
            )
        return create_engine(db_url), None, db_url, False

    resolved_db_file: Optional[str]
    db_path: Optional[Path]

    if db_file is not None:
        resolved_db_file, db_path = resolve_db_path(db_file)
    else:
        db_path = Path("./agno.db").resolve()
        resolved_db_file = str(db_path)
        log_debug(f"Created SQLite database: {db_path}")

    if not encrypted:
        return create_engine(f"sqlite:///{db_path}"), resolved_db_file, None, False

    sqlcipher3 = _import_sqlcipher3()
    escaped = escape_sqlite_string_literal(resolved_passphrase)  # type: ignore[arg-type]

    def creator() -> object:
        conn = sqlcipher3.connect(str(db_path))
        _apply_sqlcipher_pragma_sync(conn, resolved_passphrase)  # type: ignore[arg-type]
        return conn

    engine = create_engine(
        "sqlite://",
        creator=creator,
        connect_args={"check_same_thread": False},
    )
    _register_sqlcipher_pragma_listener(engine, resolved_passphrase)  # type: ignore[arg-type]
    return engine, resolved_db_file, None, True


def create_async_sqlite_engine(
    *,
    db_file: Optional[str] = None,
    db_url: Optional[str] = None,
    passphrase: Optional[str] = None,
    passphrase_env: Optional[str] = None,
) -> Tuple["AsyncEngine", Optional[str], Optional[str], bool]:
    """Create an async SQLAlchemy engine for SQLite or SQLCipher.

    When encrypted, uses ``aiosqlcipher`` with SQLAlchemy's ``async_creator`` hook.
    """
    resolved_passphrase, encrypted = resolve_passphrase(passphrase, passphrase_env)

    if db_url is not None:
        if encrypted:
            raise ValueError(
                "Cannot combine SQLCipher passphrase with db_url. "
                "Use db_file with passphrase, or supply a pre-configured db_engine."
            )
        return create_async_engine(db_url), None, db_url, False

    resolved_db_file: Optional[str]
    db_path: Optional[Path]

    if db_file is not None:
        resolved_db_file, db_path = resolve_db_path(db_file)
    else:
        db_path = Path("./agno.db").resolve()
        resolved_db_file = str(db_path)
        log_debug(f"Created SQLite database: {db_path}")

    if not encrypted:
        return create_async_engine(f"sqlite+aiosqlite:///{db_path}"), resolved_db_file, None, False

    aiosqlcipher = _import_aiosqlcipher()
    escaped = escape_sqlite_string_literal(resolved_passphrase)  # type: ignore[arg-type]
    db_path_str = str(db_path)

    async def async_creator():
        conn = await aiosqlcipher.connect(db_path_str)
        await conn.execute(f"PRAGMA key = '{escaped}'")
        return conn

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        async_creator=async_creator,
    )
    return engine, resolved_db_file, None, True
