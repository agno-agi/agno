def _strip_backtick_identifier_quotes(query: str) -> str:
    """Accept legacy backtick identifiers without changing DuckDB SQL data."""
    import duckdb

    # Token positions are UTF-8 byte offsets, not Python character indexes.
    sql_bytes = query.encode("utf-8")
    backtick_positions = {
        start
        for start, kind in duckdb.tokenize(query)
        if kind == duckdb.token_type.operator and sql_bytes[start] == ord("`")
    }
    return bytes(byte for index, byte in enumerate(sql_bytes) if index not in backtick_positions).decode("utf-8")
