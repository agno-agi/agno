from typing import Any


def get_db_type(db: Any) -> str:
    """Get the name of the agno database class the given db is, or subclasses.

    Migrations choose their SQL by this name, so a subclass of e.g. PostgresDb resolves
    to "PostgresDb" and gets the same migrations. A class with no agno database class
    in its MRO keeps its own name.

    Args:
        db: The database instance

    Returns:
        The database type name (e.g., "PostgresDb", "MySQLDb", "SqliteDb")
    """
    for cls in type(db).__mro__:
        if cls.__module__.startswith("agno.db.") and cls.__module__ != "agno.db.base":
            return cls.__name__
    return type(db).__name__


def quote_db_identifier(db_type: str, identifier: str) -> str:
    """Add the right quotes to the given identifier string (table name, schema name) based on db type.

    Args:
        db_type: The database type name (e.g., "PostgresDb", "MySQLDb", "SqliteDb")
        identifier: The identifier string to add quotes to

    Returns:
        The properly quoted identifier string
    """
    if db_type in ("MySQLDb", "AsyncMySQLDb", "SingleStoreDb"):
        escaped = identifier.replace("`", "``")
        return f"`{escaped}`"
    else:
        # Postgres, SQLite, and unknown types all use double-quote identifiers
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'
