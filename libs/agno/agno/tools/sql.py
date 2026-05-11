import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union
from urllib.parse import quote_plus

from agno.tools import Toolkit
from agno.tools._security import (
    assert_read_only_sql,
    redact_password,
    unwrap_secret,
)
from agno.utils.log import log_debug, log_warning, logger

try:
    from sqlalchemy import Engine, create_engine, event
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed")

if TYPE_CHECKING:
    from pydantic import SecretStr


def _apply_engine_read_only(engine: "Engine") -> None:
    """Best-effort engine-level read-only enforcement.

    This is defense-in-depth on top of the regex check in
    :func:`assert_read_only_sql`: even if an attacker smuggles a
    DML/DDL statement past the regex, the database refuses to
    execute it because the connection is read-only at the engine
    level.

    Strategies per dialect:

    * ``postgresql``: ``SET SESSION CHARACTERISTICS AS TRANSACTION
      READ ONLY`` + ``default_transaction_read_only = on`` on every
      new connection.
    * ``sqlite``: ``PRAGMA query_only = ON`` on every new connection.
    * ``mysql`` / ``mariadb``: ``SET SESSION TRANSACTION READ ONLY``
      on every new connection.
    * Other dialects: logged as unsupported; the regex check remains
      the only line of defense. Operators should route through a
      read-only database user for full protection.
    """
    dialect_name = (engine.dialect.name or "").lower()

    if dialect_name == "postgresql":

        @event.listens_for(engine, "connect")
        def _pg_ro(dbapi_connection, _conn_record):  # pragma: no cover - runtime hook
            cur = dbapi_connection.cursor()
            try:
                cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
                cur.execute("SET default_transaction_read_only = on")
            finally:
                cur.close()

        return

    if dialect_name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_ro(dbapi_connection, _conn_record):  # pragma: no cover
            cur = dbapi_connection.cursor()
            try:
                cur.execute("PRAGMA query_only = ON")
            finally:
                cur.close()

        return

    if dialect_name in ("mysql", "mariadb"):

        @event.listens_for(engine, "connect")
        def _mysql_ro(dbapi_connection, _conn_record):  # pragma: no cover
            cur = dbapi_connection.cursor()
            try:
                cur.execute("SET SESSION TRANSACTION READ ONLY")
            finally:
                cur.close()

        return

    log_warning(
        "SQLTools: engine-level read-only enforcement is not "
        f"implemented for dialect {dialect_name!r}. The regex check "
        "on run_sql_query remains active; for full protection route "
        "through a read-only database role."
    )


class SQLTools(Toolkit):
    """SQL toolkit (SQLAlchemy).

    Security notes (hardened build):

    * ``read_only`` defaults to ``True`` and is enforced at two
      layers:

        1. A regex rejects anything that is not a single ``SELECT``
           / ``WITH`` in :meth:`run_sql_query`.
        2. The engine is configured so that every new connection
           is put into read-only mode at the database level
           (Postgres ``default_transaction_read_only``, SQLite
           ``PRAGMA query_only``, MySQL/MariaDB
           ``SET SESSION TRANSACTION READ ONLY``).

      Even if a DML statement slips past the regex, the database
      refuses to execute it. For dialects we cannot auto-configure
      the regex remains the only line of defense; operators should
      route through a read-only database role.

      The lower-level :meth:`run_sql` remains unchecked (but still
      inherits the engine-level read-only) and is intended for
      trusted callers only — never expose it as an LLM tool.
    * ``password`` accepts either ``pydantic.SecretStr`` or a plain
      string. It is URL-encoded before being interpolated into a
      connection URL and is always redacted from ``__repr__``.
    * User and password are URL-encoded via :func:`urllib.parse.quote_plus`
      so ``:`` / ``@`` / ``/`` in credentials do not corrupt the URL.

    Args:
        db_url: An existing SQLAlchemy URL to connect with.
        db_engine: An existing SQLAlchemy ``Engine`` to reuse.
        user: Database username.
        password: Database password (``SecretStr`` recommended).
        host: Database server hostname.
        port: Database server port.
        schema: Optional default schema.
        dialect: SQLAlchemy dialect, e.g. ``"postgresql+psycopg"``.
        tables: Optional pre-baked mapping returned by
            :meth:`list_tables`; skips the live inspection call.
        read_only: When True (default), write statements are
            rejected by :meth:`run_sql_query`.
        enable_list_tables: Register :meth:`list_tables`.
        enable_describe_table: Register :meth:`describe_table`.
        enable_run_sql_query: Register :meth:`run_sql_query`.
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        user: Optional[str] = None,
        password: Optional[Union[str, "SecretStr"]] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
        tables: Optional[Dict[str, Any]] = None,
        read_only: bool = True,
        enable_list_tables: bool = True,
        enable_describe_table: bool = True,
        enable_run_sql_query: bool = True,
        all: bool = False,
        **kwargs,
    ):
        password_plain = unwrap_secret(password)

        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)
        elif user and password_plain and host and port and dialect:
            user_enc = quote_plus(user)
            pw_enc = quote_plus(password_plain)
            if schema is not None:
                _engine = create_engine(f"{dialect}://{user_enc}:{pw_enc}@{host}:{port}/{schema}")
            else:
                _engine = create_engine(f"{dialect}://{user_enc}:{pw_enc}@{host}:{port}")

        if _engine is None:
            raise ValueError("Could not build the database connection")

        self.db_engine: Engine = _engine
        self.Session: sessionmaker[Session] = sessionmaker(bind=self.db_engine)
        self.schema = schema
        self.tables: Optional[Dict[str, Any]] = tables
        self.read_only: bool = bool(read_only)
        self._user: Optional[str] = user
        self._host: Optional[str] = host
        self._port: Optional[int] = port
        self._has_password: bool = password_plain is not None

        if self.read_only:
            try:
                _apply_engine_read_only(self.db_engine)
            except Exception:  # pragma: no cover - never crash init
                logger.exception(
                    "SQLTools: failed to apply engine-level "
                    "read-only enforcement; the regex check on "
                    "run_sql_query is still active."
                )

        tools: List[Any] = []
        if enable_list_tables or all:
            tools.append(self.list_tables)
        if enable_describe_table or all:
            tools.append(self.describe_table)
        if enable_run_sql_query or all:
            tools.append(self.run_sql_query)

        super().__init__(name="sql_tools", tools=tools, **kwargs)

    def __repr__(self) -> str:
        return (
            f"SQLTools(user={self._user!r}, host={self._host!r}, "
            f"port={self._port!r}, schema={self.schema!r}, "
            f"read_only={self.read_only!r}, "
            f"password={redact_password(self._has_password and '_')!r})"
        )

    def list_tables(self) -> str:
        """Use this function to get a list of table names in the database.

        Returns:
            str: list of tables in the database.
        """
        if self.tables is not None:
            return json.dumps(self.tables)

        try:
            log_debug("listing tables in the database")
            inspector = inspect(self.db_engine)
            if self.schema:
                table_names = inspector.get_table_names(schema=self.schema)
            else:
                table_names = inspector.get_table_names()
            log_debug(f"table_names: {table_names}")
            return json.dumps(table_names)
        except Exception as e:
            logger.exception("Error getting tables")
            return f"Error getting tables: {e}"

    def describe_table(self, table_name: str) -> str:
        """Use this function to describe a table.

        Args:
            table_name (str): The name of the table to get the schema for.

        Returns:
            str: schema of a table
        """

        try:
            log_debug(f"Describing table: {table_name}")
            inspector = inspect(self.db_engine)
            table_schema = inspector.get_columns(table_name, schema=self.schema)
            return json.dumps(
                [
                    {
                        "name": column["name"],
                        "type": str(column["type"]),
                        "nullable": column["nullable"],
                        "default": column.get("default"),
                    }
                    for column in table_schema
                ]
            )
        except Exception as e:
            logger.exception("Error getting table schema")
            return f"Error getting table schema: {e}"

    def run_sql_query(self, query: str, limit: Optional[int] = 10) -> str:
        """Use this function to run a SQL query and return the result.

        Args:
            query (str): The query to run.
            limit (int, optional): The number of rows to return. Defaults to 10. Use `None` to show all results.
        Returns:
            str: Result of the SQL query.
        Notes:
            - The result may be empty if the query does not return any data.
        """
        if self.read_only:
            try:
                assert_read_only_sql(query)
            except ValueError as e:
                log_warning(f"SQLTools rejected query: {e}")
                return f"Error: {e}"

        try:
            return json.dumps(self.run_sql(sql=query, limit=limit), default=str)
        except Exception as e:
            logger.exception("Error running query")
            return f"Error running query: {e}"

    def run_sql(self, sql: str, limit: Optional[int] = None) -> List[dict]:
        """Internal function to run a sql query.

        Args:
            sql (str): The sql query to run.
            limit (int, optional): The number of rows to return. Defaults to None.

        Returns:
            List[dict]: The result of the query.
        """
        log_debug(f"Running sql |\n{sql}")

        with self.Session() as sess, sess.begin():
            result = sess.execute(text(sql))

            # DML (INSERT/UPDATE/DELETE) and DDL don't return rows — don't
            # try to fetch. The `sess.begin()` context still commits on
            # clean exit.
            if not result.returns_rows:
                return []

            try:
                if limit:
                    rows = result.fetchmany(limit)
                else:
                    rows = result.fetchall()
                return [row._asdict() for row in rows]
            except Exception:
                logger.exception("Error while executing SQL")
                return []
