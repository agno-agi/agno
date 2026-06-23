import json
import threading
from os import getenv
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from agno.databricks.utils import normalize_host
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

BLOCKED_PREFIXES = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "CREATE",
    "ALTER",
    "DROP",
    "TRUNCATE",
    "COPY",
    "GRANT",
    "REVOKE",
    "USE",
    "CALL",
    "OPTIMIZE",
    "VACUUM",
    "REPAIR",
)


def _get_databricks_sql_module():
    try:
        from databricks import sql  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "`databricks-sql-connector` not installed. Please install using `pip install databricks-sql-connector`."
        ) from exc
    return sql


class DatabricksSQLTools(Toolkit):
    """A read-only toolkit for interacting with Databricks SQL warehouses."""

    _requires_connect: bool = True

    def __init__(
        self,
        server_hostname: Optional[str] = None,
        http_path: Optional[str] = None,
        access_token: Optional[str] = None,
        connection: Optional[Any] = None,
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
        session_configuration: Optional[Dict[str, str]] = None,
        max_rows: int = 100,
        enable_list_catalogs: bool = True,
        enable_list_schemas: bool = True,
        enable_list_tables: bool = True,
        enable_describe_table: bool = True,
        enable_run_sql_query: bool = True,
        enable_explain_sql_query: bool = True,
        all: bool = False,  # noqa: A002
        **kwargs,
    ):
        self.server_hostname = self._normalize_server_hostname(
            server_hostname or getenv("DATABRICKS_SERVER_HOSTNAME") or getenv("DATABRICKS_HOST")
        )
        self.http_path = http_path or getenv("DATABRICKS_HTTP_PATH")
        self.access_token = access_token or getenv("DATABRICKS_TOKEN") or getenv("DATABRICKS_PAT")
        self.catalog = catalog or getenv("DATABRICKS_CATALOG")
        self.schema = schema or getenv("DATABRICKS_SCHEMA")
        self.session_configuration = session_configuration or {}
        self.max_rows = max_rows
        self._connection = connection
        self._connection_lock = threading.Lock()

        tools: List[Any] = []
        if enable_list_catalogs or all:
            tools.append(self.list_catalogs)
        if enable_list_schemas or all:
            tools.append(self.list_schemas)
        if enable_list_tables or all:
            tools.append(self.list_tables)
        if enable_describe_table or all:
            tools.append(self.describe_table)
        if enable_run_sql_query or all:
            tools.append(self.run_sql_query)
        if enable_explain_sql_query or all:
            tools.append(self.explain_sql_query)

        instructions = kwargs.pop(
            "instructions",
            "Use these tools for read-only Databricks SQL access. Do not attempt INSERT, UPDATE, DELETE, DDL, or multi-statement SQL.",
        )
        add_instructions = kwargs.pop("add_instructions", True)

        super().__init__(
            name="databricks_sql_tools",
            tools=tools,
            instructions=instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    def connect(self) -> Any:
        """Establish a Databricks SQL connection."""
        with self._connection_lock:
            if self._connection is not None:
                closed = getattr(self._connection, "closed", False)
                if not closed:
                    log_debug("Connection already established, reusing existing Databricks SQL connection")
                    return self._connection

            if not self.server_hostname:
                raise ValueError("server_hostname is required to connect to Databricks SQL")
            if not self.http_path:
                raise ValueError("http_path is required to connect to Databricks SQL")
            if not self.access_token:
                raise ValueError("access_token is required to connect to Databricks SQL")

            sql = _get_databricks_sql_module()
            connection_kwargs: Dict[str, Any] = {
                "server_hostname": self.server_hostname,
                "http_path": self.http_path,
                "access_token": self.access_token,
            }
            if self.session_configuration:
                connection_kwargs["session_configuration"] = self.session_configuration

            self._connection = sql.connect(**connection_kwargs)
            return self._connection

    def close(self) -> None:
        """Close the Databricks SQL connection."""
        with self._connection_lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception:
                    pass
                self._connection = None

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and not getattr(self._connection, "closed", False)

    def _ensure_connection(self) -> Any:
        if not self.is_connected:
            return self.connect()
        return self._connection

    def list_catalogs(self, limit: int = 100) -> str:
        """Use this function to list visible Databricks catalogs."""
        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                cursor.catalogs()
                rows = self._fetch_rows(cursor, limit)
                return json.dumps(rows, default=str)
        except Exception as e:
            log_error(f"Error listing Databricks catalogs: {str(e)}")
            return "Error listing Databricks catalogs: An internal error occurred. Check server logs for details."

    def list_schemas(self, catalog_name: Optional[str] = None, limit: int = 100) -> str:
        """Use this function to list schemas in a Databricks catalog."""
        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                cursor.schemas(catalog_name=catalog_name or self.catalog, schema_name="%")
                rows = self._fetch_rows(cursor, limit)
                return json.dumps(rows, default=str)
        except Exception as e:
            log_error(f"Error listing Databricks schemas: {str(e)}")
            return "Error listing Databricks schemas: An internal error occurred. Check server logs for details."

    def list_tables(
        self,
        catalog_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        table_name_pattern: Optional[str] = None,
        limit: int = 100,
    ) -> str:
        """Use this function to list tables and views in Databricks."""
        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                cursor.tables(
                    catalog_name=catalog_name or self.catalog,
                    schema_name=schema_name or self.schema,
                    table_name=table_name_pattern,
                )
                rows = self._fetch_rows(cursor, limit)
                return json.dumps(rows, default=str)
        except Exception as e:
            log_error(f"Error listing Databricks tables: {str(e)}")
            return "Error listing Databricks tables: An internal error occurred. Check server logs for details."

    def describe_table(
        self,
        table_name: str,
        catalog_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        limit: int = 200,
    ) -> str:
        """Use this function to describe the columns of a Databricks table or view."""
        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                cursor.columns(
                    catalog_name=catalog_name or self.catalog,
                    schema_name=schema_name or self.schema,
                    table_name=table_name,
                )
                rows = self._fetch_rows(cursor, limit)
                if not rows:
                    return self._describe_table_via_sql(
                        table_name=table_name,
                        catalog_name=catalog_name,
                        schema_name=schema_name,
                        limit=limit,
                    )
                return json.dumps(rows, default=str)
        except Exception as e:
            log_error(f"Error describing Databricks table: {str(e)}")
            return "Error describing Databricks table: An internal error occurred. Check server logs for details."

    def run_sql_query(self, query: str, limit: int = 100) -> str:
        """Use this function to run a read-only SQL query on Databricks SQL."""
        try:
            cleaned_query = self._validate_read_only_query(query)
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute(cleaned_query)
                return self._format_query_result(cursor, limit)
        except ValueError as e:
            return f"Error running Databricks SQL query: {e}"
        except Exception as e:
            log_error(f"Error running Databricks SQL query: {str(e)}")
            return "Error running Databricks SQL query: An internal error occurred. Check server logs for details."

    def explain_sql_query(self, query: str, limit: int = 200) -> str:
        """Use this function to inspect the execution plan for a read-only SQL query."""
        try:
            cleaned_query = self._validate_read_only_query(query)
            # Strip existing EXPLAIN prefix to avoid double-EXPLAIN
            stripped = cleaned_query.strip()
            if stripped.upper().startswith("EXPLAIN "):
                stripped = stripped[len("EXPLAIN "):].strip()
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute(f"EXPLAIN {stripped}")
                return self._format_query_result(cursor, limit)
        except ValueError as e:
            return f"Error explaining Databricks SQL query: {e}"
        except Exception as e:
            log_error(f"Error explaining Databricks SQL query: {str(e)}")
            return "Error explaining Databricks SQL query: An internal error occurred. Check server logs for details."

    def _format_query_result(self, cursor: Any, limit: int) -> str:
        if cursor.description is None:
            return json.dumps({"status": getattr(cursor, "statusmessage", "Query executed successfully.")})

        rows = self._fetch_rows(cursor, limit)
        return json.dumps(rows, default=str)

    def _describe_table_via_sql(
        self,
        table_name: str,
        catalog_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        limit: int = 200,
    ) -> str:
        qualified_name = self._qualified_table_name(
            table_name=table_name,
            catalog_name=catalog_name or self.catalog,
            schema_name=schema_name or self.schema,
        )
        connection = self._ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute(f"DESCRIBE TABLE {qualified_name}")
            rows = self._fetch_rows(cursor, limit)
            return json.dumps(rows, default=str)

    def _fetch_rows(self, cursor: Any, limit: int) -> List[Dict[str, Any]]:
        effective_limit = max(1, min(limit, self.max_rows))
        rows = cursor.fetchmany(effective_limit)
        return self._rows_to_dicts(rows, cursor.description)

    def _rows_to_dicts(self, rows: List[Any], description: Optional[Any]) -> List[Dict[str, Any]]:
        column_names = [column[0] for column in description] if description else []
        normalized_rows: List[Dict[str, Any]] = []

        for row in rows:
            if isinstance(row, dict):
                normalized_rows.append(row)
                continue
            if hasattr(row, "asDict") and callable(row.asDict):
                normalized_rows.append(row.asDict())
                continue
            if hasattr(row, "as_dict") and callable(row.as_dict):
                normalized_rows.append(row.as_dict())
                continue
            if column_names:
                try:
                    normalized_rows.append({column_names[idx]: row[idx] for idx in range(len(column_names))})
                    continue
                except Exception:
                    pass
            normalized_rows.append({"value": str(row)})

        return normalized_rows

    def _validate_read_only_query(self, query: str) -> str:
        cleaned_query = self._strip_sql_comments(query).strip()
        if cleaned_query == "":
            raise ValueError("Query cannot be empty")

        if self._has_multiple_statements(cleaned_query):
            raise ValueError("Only a single SQL statement is allowed")

        cleaned_query = cleaned_query.rstrip(";").strip()
        statement_keyword = self._get_statement_keyword(cleaned_query)
        if statement_keyword is None:
            raise ValueError("Could not determine SQL statement type")

        if statement_keyword in BLOCKED_PREFIXES:
            raise ValueError("Only read-only SQL statements are allowed")
        if statement_keyword == "EXPLAIN":
            explain_scanner = _SQLScanner(cleaned_query)
            explain_scanner.read_keyword()  # consume EXPLAIN
            # Skip EXPLAIN modifiers (ANALYZE, FORMATTED, EXTENDED, CODEGEN, COST)
            # and check the actual statement keyword that follows
            explain_modifiers = {"ANALYZE", "FORMATTED", "EXTENDED", "CODEGEN", "COST"}
            inner_keyword = explain_scanner.read_keyword()
            while inner_keyword is not None and inner_keyword in explain_modifiers:
                inner_keyword = explain_scanner.read_keyword()
            if inner_keyword is not None and inner_keyword in BLOCKED_PREFIXES:
                raise ValueError("Only read-only SQL statements are allowed")
        if statement_keyword not in {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"}:
            raise ValueError("Query must start with SELECT, WITH, SHOW, DESCRIBE, DESC, or EXPLAIN")

        return cleaned_query

    def _qualified_table_name(
        self,
        table_name: str,
        catalog_name: Optional[str],
        schema_name: Optional[str],
    ) -> str:
        parts = [part for part in [catalog_name, schema_name, table_name] if part]
        return ".".join(self._quote_identifier(part) for part in parts)

    def _quote_identifier(self, identifier: str) -> str:
        escaped = identifier.replace("`", "``")
        return f"`{escaped}`"

    def _strip_sql_comments(self, query: str) -> str:
        result: List[str] = []
        index = 0
        in_single_quote = False
        in_double_quote = False
        in_backtick = False

        while index < len(query):
            char = query[index]
            next_char = query[index + 1] if index + 1 < len(query) else ""

            if in_single_quote:
                result.append(char)
                if char == "'" and next_char == "'":
                    result.append(next_char)
                    index += 2
                    continue
                if char == "'":
                    in_single_quote = False
                index += 1
                continue

            if in_double_quote:
                result.append(char)
                if char == '"' and next_char == '"':
                    result.append(next_char)
                    index += 2
                    continue
                if char == '"':
                    in_double_quote = False
                index += 1
                continue

            if in_backtick:
                result.append(char)
                if char == "`":
                    in_backtick = False
                index += 1
                continue

            if char == "-" and next_char == "-":
                index += 2
                while index < len(query) and query[index] not in "\r\n":
                    index += 1
                continue

            if char == "/" and next_char == "*":
                depth = 1
                index += 2
                while index + 1 < len(query) and depth > 0:
                    if query[index] == "/" and query[index + 1] == "*":
                        depth += 1
                        index += 2
                    elif query[index] == "*" and query[index + 1] == "/":
                        depth -= 1
                        index += 2
                    else:
                        index += 1
                result.append(" ")
                continue

            if char == "'":
                in_single_quote = True
            elif char == '"':
                in_double_quote = True
            elif char == "`":
                in_backtick = True

            result.append(char)
            index += 1

        return "".join(result)

    def _has_multiple_statements(self, query: str) -> bool:
        scanner = _SQLScanner(query)
        saw_statement_content = False

        while not scanner.at_end():
            char = scanner.peek()
            if char == ";":
                if scanner.has_non_whitespace_after(scanner.position + 1):
                    return True
                scanner.position += 1
                continue

            if not char.isspace():
                saw_statement_content = True
            scanner.advance()

        return not saw_statement_content

    def _get_statement_keyword(self, query: str) -> Optional[str]:
        scanner = _SQLScanner(query)
        keyword = scanner.read_keyword()
        if keyword is None:
            return None

        if keyword != "WITH":
            return keyword

        if scanner.match_keyword("RECURSIVE"):
            pass

        while True:
            cte_name = scanner.read_identifier()
            if cte_name is None:
                return None

            scanner.skip_whitespace()
            if scanner.peek() == "(":
                if not scanner.consume_balanced("(", ")"):
                    return None

            if scanner.match_keyword("MAX"):
                if not scanner.match_keyword("RECURSION"):
                    return None
                if not scanner.match_keyword("LEVEL"):
                    return None
                if scanner.read_identifier() is None:
                    return None

            if scanner.match_keyword("AS"):
                pass

            scanner.skip_whitespace()
            if scanner.peek() != "(":
                return None
            if not scanner.consume_balanced("(", ")"):
                return None

            scanner.skip_whitespace()
            if scanner.peek() == ",":
                scanner.position += 1
                continue
            break

        return scanner.read_keyword()

    def _normalize_server_hostname(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        normalized = normalize_host(value)
        if normalized is None:
            return None

        parsed = urlparse(normalized)
        return parsed.netloc or normalized


class _SQLScanner:
    def __init__(self, query: str):
        self.query = query
        self.position = 0

    def at_end(self) -> bool:
        return self.position >= len(self.query)

    def peek(self) -> str:
        return "" if self.at_end() else self.query[self.position]

    def advance(self) -> None:
        if self.at_end():
            return

        char = self.query[self.position]
        if char == "'":
            self._consume_single_quote()
            return
        if char == '"':
            self._consume_double_quote()
            return
        if char == "`":
            self._consume_backtick()
            return

        self.position += 1

    def skip_whitespace(self) -> None:
        while not self.at_end() and self.query[self.position].isspace():
            self.position += 1

    def has_non_whitespace_after(self, start: int) -> bool:
        return any(not char.isspace() for char in self.query[start:])

    def read_keyword(self) -> Optional[str]:
        token = self.read_identifier()
        return token.upper() if token else None

    def match_keyword(self, keyword: str) -> bool:
        saved_position = self.position
        token = self.read_keyword()
        if token == keyword:
            return True
        self.position = saved_position
        return False

    def read_identifier(self) -> Optional[str]:
        self.skip_whitespace()
        if self.at_end():
            return None

        char = self.peek()
        if char == "`":
            return self._read_backtick_identifier()

        if not (char.isalpha() or char == "_"):
            return None

        start = self.position
        self.position += 1
        while not self.at_end() and (self.query[self.position].isalnum() or self.query[self.position] == "_"):
            self.position += 1
        return self.query[start:self.position]

    def consume_balanced(self, open_char: str, close_char: str) -> bool:
        self.skip_whitespace()
        if self.peek() != open_char:
            return False

        depth = 0
        while not self.at_end():
            char = self.peek()
            if char == "'":
                self._consume_single_quote()
                continue
            if char == '"':
                self._consume_double_quote()
                continue
            if char == "`":
                self._consume_backtick()
                continue
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
            self.position += 1
            if depth == 0:
                return True

        return False

    def _read_backtick_identifier(self) -> Optional[str]:
        if self.peek() != "`":
            return None
        self.position += 1
        start = self.position
        while not self.at_end():
            if self.query[self.position] == "`":
                identifier = self.query[start:self.position]
                self.position += 1
                return identifier
            self.position += 1
        return None

    def _consume_single_quote(self) -> None:
        self.position += 1
        while not self.at_end():
            if self.query[self.position] == "'" and self._peek_next() == "'":
                self.position += 2
                continue
            if self.query[self.position] == "'":
                self.position += 1
                return
            self.position += 1

    def _consume_double_quote(self) -> None:
        self.position += 1
        while not self.at_end():
            if self.query[self.position] == '"' and self._peek_next() == '"':
                self.position += 2
                continue
            if self.query[self.position] == '"':
                self.position += 1
                return
            self.position += 1

    def _consume_backtick(self) -> None:
        self.position += 1
        while not self.at_end():
            if self.query[self.position] == "`":
                self.position += 1
                return
            self.position += 1

    def _peek_next(self) -> str:
        if self.position + 1 >= len(self.query):
            return ""
        return self.query[self.position + 1]
