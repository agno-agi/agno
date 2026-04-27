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


def test_search_content_finds_matches():
    """Test that search_content finds files containing the query string."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        (base_dir / "hello.txt").write_text("Hello World, this is a test file")
        (base_dir / "other.py").write_text("def greet():\n    print('hello')")
        (base_dir / "nope.txt").write_text("nothing relevant here")

        result = file_tools.search_content(query="hello")
        data = json.loads(result)

        assert data["query"] == "hello"
        assert data["matches_found"] == 2
        file_names = [m["file"] for m in data["files"]]
        assert "hello.txt" in file_names
        assert "other.py" in file_names


def test_search_content_directory_scoping():
    """Test that search_content respects directory scoping."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        (base_dir / "root.txt").write_text("target text here")
        subdir = base_dir / "sub"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("target text also here")

        result = file_tools.search_content(query="target", directory="sub")
        data = json.loads(result)

        assert data["matches_found"] == 1
        assert data["files"][0]["file"] == "sub/nested.txt"


def test_search_content_no_matches():
    """Test that search_content returns zero matches when query is not found."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        (base_dir / "file.txt").write_text("some content")

        result = file_tools.search_content(query="nonexistent_string_xyz")
        data = json.loads(result)

        assert data["matches_found"] == 0
        assert data["files"] == []


def test_search_content_limit():
    """Test that search_content respects the limit parameter."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        for i in range(5):
            (base_dir / f"file{i}.txt").write_text("common string in all files")

        result = file_tools.search_content(query="common string", limit=2)
        data = json.loads(result)

        assert data["matches_found"] == 2


def test_default_exclude_patterns_hide_junk():
    """By default, .venv and similar noise dirs are excluded from results."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        tmp_sub = base_dir / "tmp"
        tmp_sub.mkdir()
        (tmp_sub / "foo.txt").write_text("foo")
        venv_pkg = tmp_sub / ".venv" / "lib" / "site-packages"
        venv_pkg.mkdir(parents=True)
        (venv_pkg / "x.py").write_text("print('x')")

        search_result = json.loads(file_tools.search_files(pattern="**/*.py"))
        assert search_result["matches_found"] == 0

        listed = json.loads(file_tools.list_files(directory="tmp"))
        assert ".venv" not in [Path(p).name for p in listed]
        assert "tmp/foo.txt" in listed


def test_empty_exclude_patterns_opts_out():
    """exclude_patterns=[] restores prior behavior: no exclusions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir, exclude_patterns=[])

        venv_pkg = base_dir / ".venv" / "lib" / "site-packages"
        venv_pkg.mkdir(parents=True)
        (venv_pkg / "x.py").write_text("print('x')")

        search_result = json.loads(file_tools.search_files(pattern="**/*.py"))
        assert search_result["matches_found"] == 1
        assert any(".venv" in p for p in search_result["files"])


def test_custom_exclude_patterns():
    """Custom patterns replace the default list."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir, exclude_patterns=["node_modules"])

        (base_dir / "node_modules").mkdir()
        (base_dir / "node_modules" / "a.txt").write_text("a")
        (base_dir / ".venv").mkdir()
        (base_dir / ".venv" / "b.txt").write_text("b")

        result = json.loads(file_tools.search_files(pattern="**/*.txt"))
        files = result["files"]
        assert not any("node_modules" in p for p in files)
        assert any(".venv" in p for p in files)


def test_exclude_patterns_match_nested_components():
    """Patterns match on any path component, not just top-level dirs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir, exclude_patterns=[".git"])

        nested = base_dir / "vendor" / "thing" / ".git"
        nested.mkdir(parents=True)
        (nested / "config").write_text("[core]")
        (base_dir / "vendor" / "thing" / "readme.txt").write_text("hi")

        result = json.loads(file_tools.search_files(pattern="**/*"))
        files = result["files"]
        assert not any(".git" in Path(p).parts for p in files)
        assert "vendor/thing/readme.txt" in files


def test_exclude_patterns_support_globs():
    """Glob patterns like '*.egg-info' are honored."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir, exclude_patterns=["*.egg-info"])

        egg = base_dir / "foo.egg-info"
        egg.mkdir()
        (egg / "PKG-INFO").write_text("Name: foo")
        (base_dir / "keep.txt").write_text("keep")

        result = json.loads(file_tools.search_files(pattern="**/*"))
        files = result["files"]
        assert not any("egg-info" in p for p in files)
        assert "keep.txt" in files


def test_default_excludes_env_family():
    """The '.env*' and '*.env' default patterns together hide both prefix
    (.env.local) and suffix (local.env) naming conventions for env files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        # Prefix convention (Next.js / Vite / most modern web frameworks)
        (base_dir / ".env").write_text("SECRET=1")
        (base_dir / ".env.local").write_text("SECRET=2")
        (base_dir / ".env.production").write_text("SECRET=3")
        (base_dir / ".envrc").write_text("export FOO=bar")

        # Suffix convention (Docker Compose --env-file, shell scripts)
        (base_dir / "local.env").write_text("SECRET=4")
        (base_dir / "prod.env").write_text("SECRET=5")

        # Real code that happens to contain "env" - must stay visible
        (base_dir / "environment.py").write_text("import os")
        (base_dir / "env.yaml").write_text("key: value")
        (base_dir / "keep.txt").write_text("visible")

        listed = sorted(json.loads(file_tools.list_files()))
        assert listed == ["env.yaml", "environment.py", "keep.txt"]


def test_search_content_honors_exclusions():
    """search_content should not return matches inside excluded directories."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        file_tools = FileTools(base_dir=base_dir)

        venv_pkg = base_dir / ".venv" / "lib"
        venv_pkg.mkdir(parents=True)
        (venv_pkg / "hit.py").write_text("# TODO: something")
        (base_dir / "real.py").write_text("# TODO: real work")

        result = json.loads(file_tools.search_content(query="TODO"))
        file_names = [m["file"] for m in result["files"]]
        assert result["matches_found"] == 1
        assert "real.py" in file_names
        assert not any(".venv" in f for f in file_names)
