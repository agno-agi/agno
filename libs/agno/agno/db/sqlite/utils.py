from typing import Optional

from agno.db.sqlite.schemas import get_table_schema_definition
from agno.utils.log import log_debug, log_error, log_warning

try:
    from sqlalchemy import Table
    from sqlalchemy.engine import Engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


def apply_sorting(stmt, table: Table, sort_by: Optional[str] = None, sort_order: Optional[str] = None):
    """Apply sorting to the given SQLAlchemy statement.
    Args:
        stmt: The SQLAlchemy statement to modify
        table: The table being queried
        sort_by: The field to sort by
        sort_order: The sort order ('asc' or 'desc')
    Returns:
        The modified statement with sorting applied
    """
    if sort_by is None or not hasattr(table.c, sort_by):
        log_debug(f"Invalid sort field: '{sort_by}'. Will not apply any sorting.")
        return stmt
    # Apply the given sorting
    sort_column = getattr(table.c, sort_by)
    if sort_order and sort_order == "asc":
        return stmt.order_by(sort_column.asc())
    else:
        return stmt.order_by(sort_column.desc())


def is_table_available(session: Session, table_name: str, db_schema: Optional[str] = None) -> bool:
    """
    Check if a table with the given name exists.
    Note: db_schema parameter is ignored in SQLite but kept for API compatibility.
    Returns:
        bool: True if the table exists, False otherwise.
    """
    try:
        # SQLite uses sqlite_master instead of information_schema
        exists_query = text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table")
        exists = session.execute(exists_query, {"table": table_name}).scalar() is not None
        if not exists:
            log_debug(f"Table {table_name} {'exists' if exists else 'does not exist'}")
        return exists
    except Exception as e:
        log_error(f"Error checking if table exists: {e}")
        return False


def is_valid_table(db_engine: Engine, table_name: str, table_type: str, db_schema: Optional[str] = None) -> bool:
    """
    Check if the existing table has the expected column names.
    Note: db_schema parameter is ignored in SQLite but kept for API compatibility.
    Args:
        db_engine (Engine): Database engine
        table_name (str): Name of the table to validate
        table_type (str): Type of table to get expected schema
        db_schema (Optional[str]): Database schema name (ignored in SQLite)
    Returns:
        bool: True if table has all expected columns, False otherwise
    """
    try:
        expected_table_schema = get_table_schema_definition(table_type)
        expected_columns = {col_name for col_name in expected_table_schema.keys() if not col_name.startswith("_")}

        # Get existing columns (no schema parameter for SQLite)
        inspector = inspect(db_engine)
        existing_columns_info = inspector.get_columns(table_name)  # No schema parameter
        existing_columns = set(col["name"] for col in existing_columns_info)

        # Check if all expected columns exist
        missing_columns = expected_columns - existing_columns
        if missing_columns:
            log_warning(f"Missing columns {missing_columns} in table {table_name}")
            return False

        log_debug(f"Table {table_name} has all expected columns")
        return True
    except Exception as e:
        log_error(f"Error validating table schema for {table_name}: {e}")
        return False
