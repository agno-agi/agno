import tempfile
from pathlib import Path

from agno.tools.local_file_system import LocalFileSystemTools


def test_write_file_writes_inside_target_directory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = LocalFileSystemTools(target_directory=tmp_dir)

        result = tools.write_file("hello", filename="report")

        assert "Successfully wrote file" in result
        assert (Path(tmp_dir) / "report.txt").read_text() == "hello"


def test_write_file_allows_relative_directory_inside_target_directory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = LocalFileSystemTools(target_directory=tmp_dir)

        result = tools.write_file("hello", filename="report", directory="nested")

        assert "Successfully wrote file" in result
        assert (Path(tmp_dir) / "nested" / "report.txt").read_text() == "hello"


def test_write_file_blocks_filename_path_escape():
    with tempfile.TemporaryDirectory() as tmp_dir:
        target_dir = Path(tmp_dir) / "target"
        target_dir.mkdir()
        tools = LocalFileSystemTools(target_directory=str(target_dir))

        result = tools.write_file("boom", filename="../escaped", extension="txt")

        assert "Error" in result
        assert "outside" in result
        assert not (Path(tmp_dir) / "escaped.txt").exists()


def test_write_file_blocks_directory_path_escape():
    with tempfile.TemporaryDirectory() as tmp_dir:
        target_dir = Path(tmp_dir) / "target"
        target_dir.mkdir()
        tools = LocalFileSystemTools(target_directory=str(target_dir))

        result = tools.write_file("boom", filename="report", directory="../outside")

        assert "Error" in result
        assert "outside" in result
        assert not (Path(tmp_dir) / "outside").exists()
