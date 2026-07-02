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
