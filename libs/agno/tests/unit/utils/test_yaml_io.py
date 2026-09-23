from agno.utils.yaml_io import read_yaml_file, write_yaml_file


def test_yaml_io_reads_utf8_non_ascii(tmp_path, cp1252_default_encoding):
    path = tmp_path / "cfg.yaml"
    path.write_bytes("name: café\ncity: São Paulo\n".encode("utf-8"))

    loaded = read_yaml_file(path)

    assert loaded == {"name": "café", "city": "São Paulo"}


def test_yaml_io_writes_utf8(tmp_path, cp1252_default_encoding):
    path = tmp_path / "out.yaml"
    write_yaml_file(path, {"name": "café"}, allow_unicode=True)

    raw = path.read_bytes()
    assert "café".encode("utf-8") in raw
    assert read_yaml_file(path) == {"name": "café"}
