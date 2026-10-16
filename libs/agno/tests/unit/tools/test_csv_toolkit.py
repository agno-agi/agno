import csv
import json
from io import StringIO

import pytest

from agno.tools.csv_toolkit import CsvTools


@pytest.mark.parametrize(
    ("columns", "rows"),
    [
        (["company", "note"], [["Acme, Inc.", "line one\nline two"], ['Say "hello"', "München"]]),
        (["company,name", 'note"text'], [["Acme", "plain text"]]),
        (["note"], [["comma,value"], ['"quoted"'], ["line one\nline two"], ["line one\rline two"]]),
    ],
    ids=["field-delimiters", "header-delimiters", "single-column"],
)
def test_query_csv_file_preserves_csv_fields(tmp_path, columns, rows):
    pytest.importorskip("duckdb")
    csv_path = tmp_path / "records.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(columns)
        writer.writerows(rows)
    tools = CsvTools(csvs=[csv_path])

    result = tools.query_csv_file("records", "SELECT * FROM records")

    assert list(csv.reader(StringIO(result, newline=""))) == [columns, *rows]


@pytest.mark.parametrize("empty_result", [False, True])
def test_query_csv_file_preserves_scalar_values_and_empty_results(tmp_path, empty_result):
    pytest.importorskip("duckdb")
    csv_path = tmp_path / "records.csv"
    csv_path.write_text("value\n1\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path])
    query = "SELECT 1 AS number, TRUE AS active, NULL AS missing FROM records"
    if empty_result:
        query += " WHERE FALSE"

    result = tools.query_csv_file("records", query)

    expected = [["number", "active", "missing"]]
    if not empty_result:
        expected.append(["1", "True", "None"])
    assert list(csv.reader(StringIO(result, newline=""))) == expected


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
