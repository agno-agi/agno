import json

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
