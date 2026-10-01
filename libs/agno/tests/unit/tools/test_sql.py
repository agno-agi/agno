import pytest
from sqlalchemy import create_engine, text

from agno.tools.sql import SQLTools


@pytest.fixture
def sql_tools():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE values_table (value INTEGER)"))
        connection.execute(text("INSERT INTO values_table (value) VALUES (1), (2), (3)"))
    return SQLTools(db_engine=engine)


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (0, []),
        (-1, []),
        (2, [{"value": 1}, {"value": 2}]),
        (None, [{"value": 1}, {"value": 2}, {"value": 3}]),
    ],
)
def test_run_sql_honors_limit(sql_tools, limit, expected):
    assert sql_tools.run_sql("SELECT value FROM values_table ORDER BY value", limit=limit) == expected
