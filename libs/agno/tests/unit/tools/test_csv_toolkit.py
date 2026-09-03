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


def test_query_csv_file_blocks_reading_files_outside_allowlist(tmp_path):
    pytest.importorskip("duckdb")
    allowed = tmp_path / "allowed.csv"
    secret = tmp_path / "secret.txt"
    allowed.write_text("id,name\n1,alice\n", encoding="utf-8")
    secret.write_text("POC_SECRET_MARKER\n", encoding="utf-8")

    tools = CsvTools(
        csvs=[allowed],
        enable_read_csv_file=False,
        enable_list_csv_files=False,
        enable_get_columns=False,
        enable_query_csv_file=True,
    )

    result = tools.query_csv_file("allowed", f"SELECT content FROM read_text('{secret}')")

    # DuckDB file I/O is disabled, so the secret file cannot be read
    assert "POC_SECRET_MARKER" not in result
    assert "Error" in result


def test_query_csv_file_blocks_writing_files_outside_allowlist(tmp_path):
    pytest.importorskip("duckdb")
    allowed = tmp_path / "allowed.csv"
    out = tmp_path / "written.csv"
    allowed.write_text("id,name\n1,alice\n", encoding="utf-8")

    tools = CsvTools(csvs=[allowed])

    tools.query_csv_file(
        "allowed",
        f"COPY (SELECT 'CSVTOOLS_WRITE_BYPASS' AS marker) TO '{out}' (HEADER, DELIMITER ',')",
    )

    # COPY ... TO is blocked, so no file is written outside the allowlist
    assert not out.exists()


def test_query_csv_file_allows_legit_query_after_lockdown(tmp_path):
    pytest.importorskip("duckdb")
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("region,total\nEU,10\nUS,20\n", encoding="utf-8")
    tools = CsvTools(csvs=[csv_path])

    # A normal aggregate over the allowlisted CSV still works after the lockdown,
    # including DuckDB type auto-detection (SUM over a numeric column).
    result = tools.query_csv_file("sales", 'SELECT SUM(total) FROM "sales"')

    assert "30" in result
