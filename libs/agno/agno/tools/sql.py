import json
from typing import Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_exception

try:
    from sqlalchemy import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed")


class SQLTools(Toolkit):
    def __init__(
        self,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
        tables: Optional[Dict[str, str]] = None,
        list_tables: bool = True,
        describe_table: bool = True,
        run_sql_query: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize SQLTools for database operations.

        Args:
            db_url: Database connection URL (e.g., postgresql://user:pass@host:port/db).
            db_engine: SQLAlchemy Engine instance. Takes precedence over db_url.
            user: Database username (used with dialect/host/port).
            password: Database password.
            host: Database host.
            port: Database port.
            schema: Database schema to use.
            dialect: Database dialect (e.g., postgresql, mysql).
            tables: Dict of table names to descriptions to expose to the agent.
            list_tables: Enable listing tables. Defaults to True.
            describe_table: Enable describing table schema. Defaults to True.
            run_sql_query: Enable running arbitrary SQL. Defaults to False (security).
            all: Enable all tools. Defaults to False.
        """
        # Get the database engine
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)
        elif user and password and host and port and dialect:
            if schema is not None:
                _engine = create_engine(f"{dialect}://{user}:{password}@{host}:{port}/{schema}")
            else:
                _engine = create_engine(f"{dialect}://{user}:{password}@{host}:{port}")

        if _engine is None:
            raise ValueError("Could not build the database connection")

        # Database connection
        self.db_engine: Engine = _engine
        self.Session: sessionmaker[Session] = sessionmaker(bind=self.db_engine)

        self.schema = schema

        # Tables this toolkit can access
        self.tables: Optional[Dict[str, str]] = tables

        tools: List[Callable] = []
        if all or list_tables:
            tools.append(self.list_tables)
        if all or describe_table:
            tools.append(self.describe_table)
        if all or run_sql_query:
            tools.append(self.run_sql_query)

        super().__init__(name="sql_tools", tools=tools, **kwargs)

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
            log_exception("Error getting tables")
            return json.dumps({"error": f"Error getting tables: {e}"})

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
            log_exception("Error getting table schema")
            return json.dumps({"error": f"Error getting table schema: {e}"})

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

        try:
            return json.dumps(self.run_sql(sql=query, limit=limit), default=str)
        except Exception as e:
            log_exception("Error running query")
            return json.dumps({"error": f"Error running query: {e}"})

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
            if not result.returns_rows:  # type: ignore[attr-defined]
                return []

            try:
                if limit:
                    rows = result.fetchmany(limit)
                else:
                    rows = result.fetchall()
                return [row._asdict() for row in rows]
            except Exception:
                log_exception("Error while executing SQL")
                return []
