import json

import pytest

from agno.tools.csv_toolkit import CsvTools


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


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("SELECT note FROM notes WHERE note = 'alpha;beta'", "note\nalpha;beta"),
        ("SELECT note AS \"note;label\" FROM notes WHERE note = 'ordinary'", "note;label\nordinary"),
        ("SELECT note FROM notes WHERE note = $$alpha;beta$$", "note\nalpha;beta"),
        ("SELECT note FROM notes /* note; filter */ WHERE note = 'ordinary'", "note\nordinary"),
        ("SELECT note FROM notes -- note; filter\nWHERE note = 'ordinary'", "note\nordinary"),
    ],
    ids=["string-literal", "quoted-identifier", "dollar-quoted-string", "block-comment", "line-comment"],
)
def test_query_csv_file_preserves_embedded_semicolons(tmp_path, query, expected):
    pytest.importorskip("duckdb")
    csv_path = tmp_path / "notes.csv"
    csv_path.write_text("note\nalpha;beta\nordinary\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path])

    assert tools.query_csv_file("notes", query) == expected


@pytest.mark.parametrize("value", ["ordinary", "alpha;beta"])
def test_query_csv_file_only_executes_first_statement(tmp_path, value):
    duckdb = pytest.importorskip("duckdb")
    csv_path = tmp_path / "notes.csv"
    csv_path.write_text("note\nalpha;beta\nordinary\n", encoding="utf-8")
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE inventory AS SELECT 1 AS id")
        tools = CsvTools(csvs=[csv_path], duckdb_connection=connection)

        result = tools.query_csv_file("notes", f"SELECT note FROM notes WHERE note = '{value}'; DELETE FROM inventory")

        assert result == f"note\n{value}"
        assert connection.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 1


@pytest.mark.parametrize("query", ["", "   ", "-- no query"])
def test_query_csv_file_without_statements_returns_no_output(tmp_path, query):
    pytest.importorskip("duckdb")
    csv_path = tmp_path / "notes.csv"
    csv_path.write_text("note\nordinary\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path])

    assert tools.query_csv_file("notes", query) == "No output"
