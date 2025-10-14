"""Unit tests for GitHub tools."""

import json
import tempfile
from pathlib import Path

from agno.tools.file import FileTools


def test_list_files():
    """Test listing files."""
    wd = "."
    f = FileTools(base_dir=Path(wd))
    response = f.list_files(directory="libs")
    file_list = json.loads(response)
    assert len(file_list) > 0
    response = f.list_files()
    file_list = json.loads(response)
    assert len(file_list) > 0
    response = f.list_files(directory="..")
    file_list = json.loads(response)
    assert len(file_list) == 0
    wd = "libs"
    f = FileTools(base_dir=Path(wd))
    response = f.list_files(directory="agno")
    file_list = json.loads(response)
    assert len(file_list) > 0
    response = f.list_files()
    file_list = json.loads(response)
    assert len(file_list) > 0
    response = f.list_files(directory="..")
    file_list = json.loads(response)
    assert len(file_list) == 0


def test_read_file():
    """Test read file"""
    f = FileTools(base_dir=Path("."))
    res = f.read_file(file_name="libs/agno/tests/unit/tools/testdir/testfile")
    assert res == "testvalue\n"
    res = f.read_file(file_name="../bla")
    assert res == "Error reading file"
    fsmall = FileTools(base_dir=Path("."), max_file_length=4)
    res = fsmall.read_file(file_name="libs/agno/tests/unit/tools/testdir/testfile")
    assert res == "Error reading file: file too long. Use read_file_chunk instead"


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


def test_search_files():
    """Test search files"""
    with tempfile.TemporaryDirectory() as tempdirname:
        f = FileTools(base_dir=Path(tempdirname))
        f.save_file(contents="contents", file_name="file1.txt")
        f.save_file(contents="contents", file_name="file2.txt")
        search_res = f.search_files("*")
        parsed_result = json.loads(search_res)
        assert parsed_result["pattern"] == "*"
        assert parsed_result["matches_found"] == 2
        assert set(parsed_result["files"]) == {"file1.txt", "file2.txt"}


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
