import json
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

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
        tables: Optional[Dict[str, Any]] = None,
        list_tables: bool = True,
        describe_table: bool = True,
        run_sql_query: bool = True,
        **kwargs,
    ):
        super().__init__(name="sql_tools", **kwargs)

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

        # Tables this toolkit can access
        self.tables: Optional[Dict[str, Any]] = tables

        # Register functions in the toolkit
        if list_tables:
            self.register(self.list_tables)
        if describe_table:
            self.register(self.describe_table)
        if run_sql_query:
            self.register(self.run_sql_query)

    def list_tables(self) -> str:
        """Use this function to get a list of table names in the database.

        Returns:
            str: list of tables in the database.
        """
        if self.tables is not None:
            return json.dumps(self.tables)

        try:
            log_debug("listing tables in the database")
            table_names = inspect(self.db_engine).get_table_names()
            log_debug(f"table_names: {table_names}")
            return json.dumps(table_names)
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
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
            table_names = inspect(self.db_engine)
            table_schema = table_names.get_columns(table_name)
            return json.dumps([str(column) for column in table_schema])
        except Exception as e:
            logger.error(f"Error getting table schema: {e}")
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

        try:
            return json.dumps(self.run_sql(sql=query, limit=limit), default=str)
        except Exception as e:
            logger.error(f"Error running query: {e}")
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

            # Check if the operation has returned rows.
            try:
                if limit:
                    rows = result.fetchmany(limit)
                else:
                    rows = result.fetchall()
                return [row._asdict() for row in rows]
            except Exception as e:
                logger.error(f"Error while executing SQL: {e}")
                return []
