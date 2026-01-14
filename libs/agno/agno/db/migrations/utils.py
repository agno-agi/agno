def quote_db_identifier(db_type: str, identifier: str) -> str:
    """Add the right quotes to the given identifier string (table name, schema name) based on db type.

    Args:
        db_type: The database type name (e.g., "PostgresDb", "MySQLDb", "SqliteDb")
        identifier: The identifier string to add quotes to

    Returns:
        The properly quoted identifier string
    """
    if db_type in ("PostgresDb", "AsyncPostgresDb"):
        return f'"{identifier}"'
    elif db_type in ("MySQLDb", "AsyncMySQLDb", "SingleStoreDb"):
        return f"`{identifier}`"
    elif db_type in ("SqliteDb", "AsyncSqliteDb"):
        return f'"{identifier}"'
    else:
        # Default to double quotes for unknown types
        return f'"{identifier}"'
