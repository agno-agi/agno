import json
import tempfile
from pathlib import Path

from agno.tools.file import FileTools


def test_save_and_read_file():
    """Test saving and reading a file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        # Save a file
        content = "Hello, World!"
        result = file_tools.save_file(contents=content, file_name="test.txt")
        assert result == "test.txt"

        # Read it back
        read_content = file_tools.read_file(file_name="test.txt")
        assert read_content == content


def test_list_files_returns_relative_paths():
    """Test that list_files returns relative paths, not absolute paths."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        # Create some test files
        (base_dir / "file1.txt").write_text("content1")
        (base_dir / "file2.txt").write_text("content2")
        (base_dir / "file3.md").write_text("content3")

        # List files
        result = file_tools.list_files()
        files = json.loads(result)

        # Verify we have 3 files
        assert len(files) == 3

        # Verify all paths are relative (not absolute)
        for file_path in files:
            assert not file_path.startswith("/")
            assert not file_path.startswith(tmp_dir)
            assert file_path in ["file1.txt", "file2.txt", "file3.md"]


def test_search_files_returns_relative_paths():
    """Test that search_files returns relative paths in JSON structure."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        # Create test files in nested directories
        (base_dir / "file1.txt").write_text("content1")
        (base_dir / "file2.md").write_text("content2")
        subdir = base_dir / "subdir"
        subdir.mkdir()
        (subdir / "file3.txt").write_text("content3")

        # Search for .txt files
        result = file_tools.search_files(pattern="*.txt")
        data = json.loads(result)

        # Verify JSON structure
        assert "pattern" in data
        assert "matches_found" in data
        assert "files" in data

        assert data["pattern"] == "*.txt"
        assert data["matches_found"] == 1
        assert len(data["files"]) == 1

        # Verify paths are relative (not absolute)
        for file_path in data["files"]:
            assert not file_path.startswith("/")
            assert not file_path.startswith(tmp_dir)
            assert file_path == "file1.txt"

        # Search with recursive pattern
        result = file_tools.search_files(pattern="**/*.txt")
        data = json.loads(result)

        assert data["matches_found"] == 2
        assert len(data["files"]) == 2

        # Verify all paths are relative
        for file_path in data["files"]:
            assert not file_path.startswith("/")
            assert not file_path.startswith(tmp_dir)

        assert "file1.txt" in data["files"]
        assert "subdir/file3.txt" in data["files"]


def test_save_and_delete_file():
    with tempfile.TemporaryDirectory() as tmpdirname:
        f = FileTools(base_dir=Path(tmpdirname), enable_delete_file=True)
        res = f.save_file(contents="contents", file_name="file.txt")
        assert res == "file.txt"
        contents = f.read_file(file_name="file.txt")
        assert contents == "contents"
        result = f.delete_file(file_name="file.txt")
        assert result == ""
        contents = f.read_file(file_name="file.txt")
        assert contents != "contents"


def test_read_file_chunk():
    """Test chunked file read"""
    with tempfile.TemporaryDirectory() as tempdirname:
        f = FileTools(base_dir=Path(tempdirname))
        f.save_file(contents="line0\nline1\nline2\nline3\n", file_name="file1.txt")
        res = f.read_file_chunk(file_name="file1.txt", start_line=0, end_line=2)
        assert res == "line0\nline1\nline2"
        res = f.read_file_chunk(file_name="file1.txt", start_line=2, end_line=4)
        assert res == "line2\nline3\n"


def test_replace_file_chunk():
    """Test replace file chunk"""
    with tempfile.TemporaryDirectory() as tempdirname:
        f = FileTools(base_dir=Path(tempdirname))
        f.save_file(contents="line0\nline1\nline2\nline3\n", file_name="file1.txt")
        res = f.replace_file_chunk(file_name="file1.txt", start_line=1, end_line=2, chunk="some\nstuff")
        assert res == "file1.txt"
        new_contents = f.read_file(file_name="file1.txt")
        assert new_contents == "line0\nsome\nstuff\nline3\n"


def test_check_escape():
    """Test check_escape service function"""
    with tempfile.TemporaryDirectory() as tempdirname:
        base_dir = Path(tempdirname)
        f = FileTools(base_dir=base_dir)
        flag, path = f.check_escape(".")
        assert flag
        assert path.resolve() == base_dir.resolve()
        flag, path = f.check_escape("..")
        assert not (flag)
        flag, path = f.check_escape("a/b/..")
        assert flag
        assert path.resolve() == base_dir.joinpath(Path("a")).resolve()
        flag, path = f.check_escape("a/b/../../..")
        assert not (flag)
