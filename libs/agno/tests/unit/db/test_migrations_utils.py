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
