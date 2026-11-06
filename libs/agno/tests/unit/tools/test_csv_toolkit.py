import json

import pytest

from agno.tools.csv_toolkit import CsvTools


@pytest.mark.parametrize(
    ("constructor_limit", "requested_limit", "expected_row_count"),
    [
        (None, 0, 0),
        (1, 0, 0),
        (0, 0, 0),
        (1, None, 1),
        (0, None, 0),
        (None, None, 3),
        (0, 2, 2),
        (None, -1, 2),
    ],
    ids=[
        "explicit-zero-unbounded-default",
        "explicit-zero-positive-default",
        "explicit-zero-zero-default",
        "none-uses-positive-default",
        "none-uses-zero-default",
        "none-with-unbounded-default",
        "positive-overrides-zero-default",
        "negative-preserves-slice",
    ],
)
def test_read_csv_file_respects_explicit_zero_and_row_limit_fallback(
    tmp_path, constructor_limit, requested_limit, expected_row_count
):
    csv_path = tmp_path / "people.csv"
    csv_path.write_text("name,age\nAlice,30\nBob,40\nCara,50\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path], row_limit=constructor_limit, enable_query_csv_file=False)

    rows = json.loads(tools.read_csv_file("people", row_limit=requested_limit))

    all_rows = [
        {"name": "Alice", "age": "30"},
        {"name": "Bob", "age": "40"},
        {"name": "Cara", "age": "50"},
    ]
    assert rows == all_rows[:expected_row_count]


def test_read_csv_file_preserves_non_ascii_content(tmp_path):
    csv_path = tmp_path / "people.csv"
    csv_path.write_text("name,city\nJosé,São Paulo\n李雷,北京\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path])

    rows = json.loads(tools.read_csv_file("people"))

    assert rows == [
        {"name": "José", "city": "São Paulo"},
        {"name": "李雷", "city": "北京"},
    ]


def test_read_csv_file_handles_utf8_bom_header(tmp_path):
    csv_path = tmp_path / "people.csv"
    csv_path.write_text("\ufeffname,city\nJosé,São Paulo\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path])

    rows = json.loads(tools.read_csv_file("people"))
    columns = json.loads(tools.get_columns("people"))

    assert rows == [{"name": "José", "city": "São Paulo"}]
    assert columns == ["name", "city"]


def test_query_csv_file_quotes_hyphenated_table_name(tmp_path):
    pytest.importorskip("duckdb")
    csv_path = tmp_path / "sales-data.csv"
    csv_path.write_text("region,total\nEU,10\nUS,20\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path])

    result = tools.query_csv_file("sales-data", 'SELECT SUM(total) FROM "sales-data"')

    assert "30" in result


def test_query_csv_file_quotes_table_name_with_special_chars(tmp_path):
    pytest.importorskip("duckdb")
    csv_path = tmp_path / "2024 report#1.csv"
    csv_path.write_text("region,total\nEU,10\nUS,20\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path])

    result = tools.query_csv_file("2024 report#1", 'SELECT SUM(total) FROM "2024 report#1"')

    assert "30" in result


def test_query_csv_file_path_injection_is_neutralized(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect()
    connection.execute("CREATE TABLE inventory AS SELECT 1")

    crafted_name = "orders'; DROP TABLE inventory; --"
    csv_path = tmp_path / f"{crafted_name}.csv"
    csv_path.write_text("a\n1\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path], duckdb_connection=connection)

    tools.query_csv_file(crafted_name, f'SELECT COUNT(*) FROM "{crafted_name}"')

    # The path is bound as a parameter, so the injected statement never runs
    assert connection.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 1


def test_query_csv_file_can_run_twice_on_the_same_connection(tmp_path):
    """A reused connection must be able to query the same file again."""
    duckdb = pytest.importorskip("duckdb")

    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("region,amount\nnorth,10\nsouth,20\n", encoding="utf-8")

    connection = duckdb.connect()
    tools = CsvTools(csvs=[csv_path], duckdb_connection=connection)

    first = tools.query_csv_file("sales", "SELECT SUM(amount) FROM sales")
    second = tools.query_csv_file("sales", "SELECT SUM(amount) FROM sales")

    assert "Error" not in first
    assert "Error" not in second
    assert first == second


def test_query_csv_file_reflects_changes_on_disk(tmp_path):
    """The table is rebuilt for every query instead of keeping stale rows."""
    duckdb = pytest.importorskip("duckdb")

    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("region,amount\nnorth,10\n", encoding="utf-8")

    tools = CsvTools(csvs=[csv_path], duckdb_connection=duckdb.connect())
    assert "10" in tools.query_csv_file("sales", "SELECT SUM(amount) FROM sales")

    csv_path.write_text("region,amount\nnorth,99\n", encoding="utf-8")

    assert "99" in tools.query_csv_file("sales", "SELECT SUM(amount) FROM sales")
