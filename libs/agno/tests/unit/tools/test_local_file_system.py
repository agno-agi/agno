from agno.tools.local_file_system import LocalFileSystemTools


def test_write_file_blocks_absolute_filename_outside_target(tmp_path):
    safe_dir = tmp_path / "safe"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    tools = LocalFileSystemTools(target_directory=str(safe_dir))

    result = tools.write_file("owned", filename=str(outside_dir / "pwn"))

    assert "Error" in result
    assert "outside target directory" in result
    assert not (outside_dir / "pwn.txt").exists()


def test_write_file_blocks_directory_outside_target(tmp_path):
    safe_dir = tmp_path / "safe"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    tools = LocalFileSystemTools(target_directory=str(safe_dir))

    result = tools.write_file("owned", filename="pwn", directory=str(outside_dir))

    assert "Error" in result
    assert "outside target directory" in result
    assert not (outside_dir / "pwn.txt").exists()


def test_write_file_allows_relative_directory_inside_target(tmp_path):
    safe_dir = tmp_path / "safe"
    tools = LocalFileSystemTools(target_directory=str(safe_dir))

    result = tools.write_file("hello", filename="note", directory="nested")

    assert "Successfully wrote file" in result
    assert (safe_dir / "nested" / "note.txt").read_text() == "hello"


def test_write_file_preserves_relative_directory_already_inside_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tools = LocalFileSystemTools(target_directory="safe")

    result = tools.write_file("hello", filename="note", directory="safe")

    assert "Successfully wrote file" in result
    assert (tmp_path / "safe" / "note.txt").read_text() == "hello"
