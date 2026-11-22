import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Result

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


@pytest.mark.parametrize("limit", [None, 2])
def test_run_sql_surfaces_fetch_errors(sql_tools, limit, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated driver error during fetch")

    monkeypatch.setattr(Result, "fetchall", _boom)
    monkeypatch.setattr(Result, "fetchmany", _boom)

    with pytest.raises(RuntimeError, match="simulated driver error during fetch"):
        sql_tools.run_sql("SELECT value FROM values_table ORDER BY value", limit=limit)


@pytest.mark.parametrize("limit", [None, 2])
def test_run_sql_query_reports_fetch_errors(sql_tools, limit, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated driver error during fetch")

    monkeypatch.setattr(Result, "fetchall", _boom)
    monkeypatch.setattr(Result, "fetchmany", _boom)

    result = sql_tools.run_sql_query("SELECT value FROM values_table ORDER BY value", limit=limit)
    assert result.startswith("Error running query: ")
    assert "simulated driver error during fetch" in result
    assert result != "[]"
