from agno.db.migrations.utils import quote_db_identifier


def test_quote_db_identifier_postgres():
    """Test that quote_db_identifier uses double quotes for PostgreSQL"""
    assert quote_db_identifier("PostgresDb", "my_table") == '"my_table"'
    assert quote_db_identifier("AsyncPostgresDb", "my_schema") == '"my_schema"'


def test_quote_db_identifier_mysql():
    """Test that quote_db_identifier uses backticks for MySQL"""
    assert quote_db_identifier("MySQLDb", "my_table") == "`my_table`"
    assert quote_db_identifier("AsyncMySQLDb", "my_schema") == "`my_schema`"
    assert quote_db_identifier("SingleStoreDb", "my_table") == "`my_table`"


def test_quote_db_identifier_sqlite():
    """Test that quote_db_identifier uses double quotes for SQLite"""
    assert quote_db_identifier("SqliteDb", "my_table") == '"my_table"'
    assert quote_db_identifier("AsyncSqliteDb", "my_schema") == '"my_schema"'


def test_quote_db_identifier_unknown_defaults_to_double_quotes():
    assert quote_db_identifier("UnknownDb", "tbl") == '"tbl"'


def test_quote_db_identifier_escapes_double_quote_postgres():
    """Embedded double-quotes must be doubled for Postgres identifiers."""
    assert quote_db_identifier("PostgresDb", 'my"table') == '"my""table"'
    assert quote_db_identifier("AsyncPostgresDb", 'a"b"c') == '"a""b""c"'


def test_quote_db_identifier_escapes_double_quote_sqlite():
    """Embedded double-quotes must be doubled for SQLite identifiers."""
    assert quote_db_identifier("SqliteDb", 'my"table') == '"my""table"'
    assert quote_db_identifier("AsyncSqliteDb", 'x"y') == '"x""y"'


def test_quote_db_identifier_escapes_backtick_mysql():
    """Embedded backticks must be doubled for MySQL/SingleStore identifiers."""
    assert quote_db_identifier("MySQLDb", "my`table") == "`my``table`"
    assert quote_db_identifier("AsyncMySQLDb", "a`b`c") == "`a``b``c`"
    assert quote_db_identifier("SingleStoreDb", "t`bl") == "`t``bl`"


def test_quote_db_identifier_no_unnecessary_escaping():
    """Double-quotes in MySQL and backticks in Postgres should pass through unchanged."""
    assert quote_db_identifier("MySQLDb", 'has"quote') == '`has"quote`'
    assert quote_db_identifier("PostgresDb", "has`tick") == '"has`tick"'
