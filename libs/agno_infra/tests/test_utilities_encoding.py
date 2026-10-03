import json

from agno.utilities.json_io import read_json_file, write_json_file
from agno.utilities.yaml_io import read_yaml_file, write_yaml_file


def test_json_helpers_round_trip_utf8(tmp_path):
    path = tmp_path / "config.json"
    data = {"message": "hello \u2603"}

    write_json_file(path, data, ensure_ascii=False)

    assert json.loads(path.read_text(encoding="utf-8")) == data
    assert read_json_file(path) == data


def test_yaml_helpers_round_trip_utf8(tmp_path):
    path = tmp_path / "config.yaml"
    data = {"message": "hello \u2603"}

    write_yaml_file(path, data, allow_unicode=True)

    assert "hello \u2603" in path.read_text(encoding="utf-8")
    assert read_yaml_file(path) == data
