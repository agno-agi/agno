def quote_identifier(db_type: str, identifier: str) -> str:
    """Quote an identifier (table name, schema name) based on database type.

    Args:
        db_type: The database type name (e.g., "PostgresDb", "MySQLDb", "SqliteDb")
        identifier: The identifier to quote

    Returns:
        The quoted identifier
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
