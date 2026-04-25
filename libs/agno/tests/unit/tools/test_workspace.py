import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from agno.tools.workspace import Workspace

# All registered tool names (the descriptive names the LLM sees, after alias translation).
ALL_METHODS = [
    "read_file",
    "list_files",
    "search_content",
    "write_file",
    "edit_file",
    "delete_file",
    "run_command",
]
READ_METHODS = ["read_file", "list_files", "search_content"]
WRITE_METHODS = ["write_file", "edit_file", "delete_file", "run_command"]


# ------------------------------------------------------------------
# Constructor: partition resolution & validation
# ------------------------------------------------------------------


def test_default_partitions_when_both_none():
    """Both None → reads in allowed (auto-pass), writes in confirm."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        sync_names = list(ws.functions.keys())
        async_names = list(ws.async_functions.keys())

        # Every method registered under its descriptive name (sync + async).
        assert sorted(sync_names) == sorted(ALL_METHODS)
        assert sorted(async_names) == sorted(ALL_METHODS)

        for name in WRITE_METHODS:
            assert ws.functions[name].requires_confirmation is True
            assert ws.async_functions[name].requires_confirmation is True
        for name in READ_METHODS:
            assert ws.functions[name].requires_confirmation is False
            assert ws.async_functions[name].requires_confirmation is False


def test_only_allowed_set_makes_confirm_default_empty():
    """allowed_tools set, confirm_tools=None → confirm defaults to [], not WRITE_TOOLS."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, allowed_tools=["read"])
        assert list(ws.functions.keys()) == ["read_file"]
        assert ws.functions["read_file"].requires_confirmation is False


def test_only_confirm_set_makes_allowed_default_empty():
    """confirm_tools set, allowed_tools=None → allowed defaults to [], not READ_TOOLS."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, confirm_tools=["write"])
        assert list(ws.functions.keys()) == ["write_file"]
        assert ws.functions["write_file"].requires_confirmation is True


def test_unknown_alias_in_allowed_raises():
    with pytest.raises(ValueError, match="Unknown alias"):
        Workspace(".", allowed_tools=["read", "not_a_tool"])


def test_unknown_alias_in_confirm_raises():
    with pytest.raises(ValueError, match="Unknown alias"):
        Workspace(".", confirm_tools=["bogus"])


def test_full_method_name_in_alias_list_raises():
    """Aliases are short; passing a full method name like 'read_file' should fail loud."""
    with pytest.raises(ValueError, match="Unknown alias"):
        Workspace(".", allowed_tools=["read_file"])


def test_overlap_between_allowed_and_confirm_raises():
    with pytest.raises(ValueError, match="mutually exclusive"):
        Workspace(
            ".",
            allowed_tools=["read", "write"],
            confirm_tools=["write"],
        )


def test_empty_lists_in_both_registers_nothing():
    """Both empty lists → no methods registered (useful for tests)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, allowed_tools=[], confirm_tools=[])
        assert list(ws.functions.keys()) == []
        assert list(ws.async_functions.keys()) == []


def test_custom_partition_works():
    """User-defined partition with both lists set."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(
            tmp_dir,
            allowed_tools=["read"],
            confirm_tools=["delete"],
        )
        assert sorted(ws.functions.keys()) == ["delete_file", "read_file"]
        assert ws.functions["read_file"].requires_confirmation is False
        assert ws.functions["delete_file"].requires_confirmation is True


def test_root_kwarg_is_optional_positional():
    """Workspace('.') and Workspace(root='.') both work."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws_pos = Workspace(tmp_dir)
        ws_kw = Workspace(root=tmp_dir)
        assert ws_pos.root == ws_kw.root == Path(tmp_dir).resolve()


def test_root_defaults_to_cwd():
    ws = Workspace()
    assert ws.root == Path.cwd().resolve()


# ------------------------------------------------------------------
# Sandbox: path escape protection
# ------------------------------------------------------------------


def test_path_escape_blocked_on_read():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        result = ws.read_file("../../../etc/passwd")
        assert result.startswith("Error")


def test_path_escape_blocked_on_write():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        result = ws.write_file("../escaped.txt", "boom")
        assert result.startswith("Error")
        # File outside the sandbox should not have been created.
        assert not (Path(tmp_dir).parent / "escaped.txt").exists()


def test_path_escape_blocked_on_delete():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        # Create a sibling file outside root.
        outside = Path(tmp_dir).parent / "outside_test_file.txt"
        outside.write_text("keep me")
        try:
            result = ws.delete_file("../outside_test_file.txt")
            assert result.startswith("Error")
            assert outside.exists()
        finally:
            if outside.exists():
                outside.unlink()


# ------------------------------------------------------------------
# read_file
# ------------------------------------------------------------------


def test_read_file_full_contents():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "hello.txt").write_text("Hello, World!")
        assert ws.read_file("hello.txt") == "Hello, World!"


def test_read_file_with_line_range():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "lines.txt").write_text("a\nb\nc\nd\ne\n")
        # 1-indexed inclusive
        assert ws.read_file("lines.txt", start_line=2, end_line=4) == "b\nc\nd"


def test_read_file_missing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        result = ws.read_file("does_not_exist.txt")
        assert result.startswith("Error: file not found")


def test_read_file_too_long_by_chars():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, max_file_length=10)
        (Path(tmp_dir) / "big.txt").write_text("a" * 100)
        result = ws.read_file("big.txt")
        assert "too long" in result
        # Chunked read still works.
        assert ws.read_file("big.txt", start_line=1, end_line=1) == "a" * 100


def test_read_file_too_long_by_lines():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, max_file_lines=3)
        (Path(tmp_dir) / "many.txt").write_text("\n".join(str(i) for i in range(10)))
        result = ws.read_file("many.txt")
        assert "too long" in result


# ------------------------------------------------------------------
# list_files
# ------------------------------------------------------------------


def test_list_files_basic():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "a.txt").write_text("a")
        (Path(tmp_dir) / "b.txt").write_text("b")
        result = json.loads(ws.list_files())
        assert sorted(result["files"]) == ["a.txt", "b.txt"]


def test_list_files_with_recursive_pattern():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "a.py").write_text("a")
        sub = base / "sub"
        sub.mkdir()
        (sub / "b.py").write_text("b")
        (base / "c.txt").write_text("c")

        result = json.loads(ws.list_files(pattern="**/*.py"))
        assert sorted(result["files"]) == ["a.py", "sub/b.py"]


def test_list_files_skips_default_excludes():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "keep.txt").write_text("keep")
        (base / ".venv").mkdir()
        (base / ".venv" / "skip.txt").write_text("skip")

        result = json.loads(ws.list_files())
        assert "keep.txt" in result["files"]
        assert ".venv" not in result["files"]


def test_list_files_paths_are_relative():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "x.txt").write_text("x")
        result = json.loads(ws.list_files())
        for f in result["files"]:
            assert not f.startswith("/")
            assert not f.startswith(tmp_dir)


# ------------------------------------------------------------------
# search_content
# ------------------------------------------------------------------


def test_search_content_finds_matches():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "hello.txt").write_text("Hello World, this is a test file")
        (base / "other.py").write_text("def greet():\n    print('hello')")
        (base / "nope.txt").write_text("nothing relevant")

        result = json.loads(ws.search_content(query="hello"))
        assert result["matches_found"] == 2
        names = [m["file"] for m in result["files"]]
        assert "hello.txt" in names
        assert "other.py" in names


def test_search_content_directory_scoping():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "root.txt").write_text("target")
        sub = base / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("target also")

        result = json.loads(ws.search_content(query="target", directory="sub"))
        assert result["matches_found"] == 1
        assert result["files"][0]["file"] == "sub/nested.txt"


def test_search_content_skips_excluded_dirs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        venv_pkg = base / ".venv" / "lib"
        venv_pkg.mkdir(parents=True)
        (venv_pkg / "hit.py").write_text("# TODO: vendor")
        (base / "real.py").write_text("# TODO: real work")

        result = json.loads(ws.search_content(query="TODO"))
        names = [m["file"] for m in result["files"]]
        assert result["matches_found"] == 1
        assert "real.py" in names
        assert not any(".venv" in f for f in names)


def test_search_content_empty_query():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        assert ws.search_content(query="").startswith("Error")


# ------------------------------------------------------------------
# write_file
# ------------------------------------------------------------------


def test_write_file_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        result = ws.write_file("nested/deep/file.txt", "hi")
        assert "Wrote" in result
        assert (Path(tmp_dir) / "nested" / "deep" / "file.txt").read_text() == "hi"


def test_write_file_no_overwrite():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        ws.write_file("a.txt", "first")
        result = ws.write_file("a.txt", "second", overwrite=False)
        assert result.startswith("Error")
        assert (Path(tmp_dir) / "a.txt").read_text() == "first"


# ------------------------------------------------------------------
# edit_file
# ------------------------------------------------------------------


def test_edit_file_replaces_unique_match():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("Hello, alpha. Goodbye, beta.")
        result = ws.edit_file("doc.md", old_str="alpha", new_str="ALPHA")
        assert "replaced 1 occurrence" in result
        assert (Path(tmp_dir) / "doc.md").read_text() == "Hello, ALPHA. Goodbye, beta."


def test_edit_file_rejects_zero_matches():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("Hello, alpha.")
        result = ws.edit_file("doc.md", old_str="missing", new_str="x")
        assert "not found" in result


def test_edit_file_rejects_multiple_matches():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("foo foo foo")
        result = ws.edit_file("doc.md", old_str="foo", new_str="bar")
        assert "matches 3 times" in result
        # File untouched.
        assert (Path(tmp_dir) / "doc.md").read_text() == "foo foo foo"


# ------------------------------------------------------------------
# delete_file
# ------------------------------------------------------------------


def test_delete_file_removes_file():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        target = Path(tmp_dir) / "byebye.txt"
        target.write_text("x")
        result = ws.delete_file("byebye.txt")
        assert "Deleted" in result
        assert not target.exists()


def test_delete_file_refuses_directory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        sub = Path(tmp_dir) / "subdir"
        sub.mkdir()
        result = ws.delete_file("subdir")
        assert result.startswith("Error")
        assert sub.exists()


# ------------------------------------------------------------------
# run_command
# ------------------------------------------------------------------


def test_run_command_success():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "file_a.txt").write_text("a")
        (Path(tmp_dir) / "file_b.txt").write_text("b")
        out = ws.run_command(["ls"])
        assert "file_a.txt" in out
        assert "file_b.txt" in out


def test_run_command_runs_in_root():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        out = ws.run_command(["pwd"])
        assert out.strip() == str(Path(tmp_dir).resolve())


def test_run_command_returns_error_on_nonzero_exit():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        out = ws.run_command(["ls", "definitely-does-not-exist-xyz"])
        assert out.startswith("Error")


# ------------------------------------------------------------------
# Async siblings — spot-check parity with sync
# ------------------------------------------------------------------


def test_async_read_file_matches_sync():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "a.txt").write_text("hi")
        sync_result = ws.read_file("a.txt")
        async_result = asyncio.run(ws.aread_file("a.txt"))
        assert sync_result == async_result == "hi"


def test_async_write_then_read():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)

        async def go():
            await ws.awrite_file("a.txt", "async write")
            return await ws.aread_file("a.txt")

        assert asyncio.run(go()) == "async write"


def test_async_run_command():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "marker.txt").write_text("x")
        out = asyncio.run(ws.arun_command(["ls"]))
        assert "marker.txt" in out


# ------------------------------------------------------------------
# Excludes config
# ------------------------------------------------------------------


def test_empty_exclude_patterns_opts_out():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, exclude_patterns=[])
        venv_pkg = Path(tmp_dir) / ".venv" / "lib"
        venv_pkg.mkdir(parents=True)
        (venv_pkg / "x.py").write_text("print('x')")
        result = json.loads(ws.list_files(pattern="**/*.py"))
        assert any(".venv" in f for f in result["files"])
