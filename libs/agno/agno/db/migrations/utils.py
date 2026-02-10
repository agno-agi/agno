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
