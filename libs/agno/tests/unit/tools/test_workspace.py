import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from agno.tools.workspace import WorkspaceTools

# ------------------------------------------------------------------
# Constructor: partition resolution & validation
# ------------------------------------------------------------------


def test_default_partitions_when_both_none():
    """Both None → reads in allowed (auto-pass), writes in confirm."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        sync_names = list(wt.functions.keys())
        async_names = list(wt.async_functions.keys())

        # Every method registered (sync + async).
        assert sorted(sync_names) == sorted(WorkspaceTools.ALL_TOOLS)
        assert sorted(async_names) == sorted(WorkspaceTools.ALL_TOOLS)

        # WRITE_TOOLS require confirmation; READ_TOOLS do not.
        for name in WorkspaceTools.WRITE_TOOLS:
            assert wt.functions[name].requires_confirmation is True
            assert wt.async_functions[name].requires_confirmation is True
        for name in WorkspaceTools.READ_TOOLS:
            assert wt.functions[name].requires_confirmation is False
            assert wt.async_functions[name].requires_confirmation is False


def test_only_allowed_set_makes_confirm_default_empty():
    """allowed_tools set, confirm_tools=None → confirm defaults to [], not WRITE_TOOLS."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir, allowed_tools=["read_file"])
        assert list(wt.functions.keys()) == ["read_file"]
        assert wt.functions["read_file"].requires_confirmation is False


def test_only_confirm_set_makes_allowed_default_empty():
    """confirm_tools set, allowed_tools=None → allowed defaults to [], not READ_TOOLS."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir, confirm_tools=["write_file"])
        assert list(wt.functions.keys()) == ["write_file"]
        assert wt.functions["write_file"].requires_confirmation is True


def test_unknown_name_in_allowed_raises():
    with pytest.raises(ValueError, match="Unknown tool name"):
        WorkspaceTools(base_dir=".", allowed_tools=["read_file", "not_a_tool"])


def test_unknown_name_in_confirm_raises():
    with pytest.raises(ValueError, match="Unknown tool name"):
        WorkspaceTools(base_dir=".", confirm_tools=["bogus"])


def test_overlap_between_allowed_and_confirm_raises():
    with pytest.raises(ValueError, match="mutually exclusive"):
        WorkspaceTools(
            base_dir=".",
            allowed_tools=["read_file", "write_file"],
            confirm_tools=["write_file"],
        )


def test_empty_lists_in_both_registers_nothing():
    """Both empty lists → no methods registered (useful for tests)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir, allowed_tools=[], confirm_tools=[])
        assert list(wt.functions.keys()) == []
        assert list(wt.async_functions.keys()) == []


def test_custom_partition_works():
    """User-defined partition with both lists set."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(
            base_dir=tmp_dir,
            allowed_tools=["read_file"],
            confirm_tools=["delete_file"],
        )
        assert sorted(wt.functions.keys()) == ["delete_file", "read_file"]
        assert wt.functions["read_file"].requires_confirmation is False
        assert wt.functions["delete_file"].requires_confirmation is True


# ------------------------------------------------------------------
# Sandbox: path escape protection
# ------------------------------------------------------------------


def test_path_escape_blocked_on_read():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        result = wt.read_file("../../../etc/passwd")
        assert result.startswith("Error")


def test_path_escape_blocked_on_write():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        result = wt.write_file("../escaped.txt", "boom")
        assert result.startswith("Error")
        # File outside the sandbox should not have been created.
        assert not (Path(tmp_dir).parent / "escaped.txt").exists()


def test_path_escape_blocked_on_delete():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        # Create a sibling file outside base_dir.
        outside = Path(tmp_dir).parent / "outside_test_file.txt"
        outside.write_text("keep me")
        try:
            result = wt.delete_file("../outside_test_file.txt")
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
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "hello.txt").write_text("Hello, World!")
        assert wt.read_file("hello.txt") == "Hello, World!"


def test_read_file_with_line_range():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "lines.txt").write_text("a\nb\nc\nd\ne\n")
        # 1-indexed inclusive
        assert wt.read_file("lines.txt", start_line=2, end_line=4) == "b\nc\nd"


def test_read_file_missing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        result = wt.read_file("does_not_exist.txt")
        assert result.startswith("Error: file not found")


def test_read_file_too_long_by_chars():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir, max_file_length=10)
        (Path(tmp_dir) / "big.txt").write_text("a" * 100)
        result = wt.read_file("big.txt")
        assert "too long" in result
        # Chunked read still works.
        assert wt.read_file("big.txt", start_line=1, end_line=1) == "a" * 100


def test_read_file_too_long_by_lines():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir, max_file_lines=3)
        (Path(tmp_dir) / "many.txt").write_text("\n".join(str(i) for i in range(10)))
        result = wt.read_file("many.txt")
        assert "too long" in result


# ------------------------------------------------------------------
# list_files
# ------------------------------------------------------------------


def test_list_files_basic():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "a.txt").write_text("a")
        (Path(tmp_dir) / "b.txt").write_text("b")
        result = json.loads(wt.list_files())
        assert sorted(result["files"]) == ["a.txt", "b.txt"]


def test_list_files_with_recursive_pattern():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        base = Path(tmp_dir)
        (base / "a.py").write_text("a")
        sub = base / "sub"
        sub.mkdir()
        (sub / "b.py").write_text("b")
        (base / "c.txt").write_text("c")

        result = json.loads(wt.list_files(pattern="**/*.py"))
        assert sorted(result["files"]) == ["a.py", "sub/b.py"]


def test_list_files_skips_default_excludes():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        base = Path(tmp_dir)
        (base / "keep.txt").write_text("keep")
        (base / ".venv").mkdir()
        (base / ".venv" / "skip.txt").write_text("skip")

        result = json.loads(wt.list_files())
        assert "keep.txt" in result["files"]
        assert ".venv" not in result["files"]


def test_list_files_paths_are_relative():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "x.txt").write_text("x")
        result = json.loads(wt.list_files())
        for f in result["files"]:
            assert not f.startswith("/")
            assert not f.startswith(tmp_dir)


# ------------------------------------------------------------------
# search_content
# ------------------------------------------------------------------


def test_search_content_finds_matches():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        base = Path(tmp_dir)
        (base / "hello.txt").write_text("Hello World, this is a test file")
        (base / "other.py").write_text("def greet():\n    print('hello')")
        (base / "nope.txt").write_text("nothing relevant")

        result = json.loads(wt.search_content(query="hello"))
        assert result["matches_found"] == 2
        names = [m["file"] for m in result["files"]]
        assert "hello.txt" in names
        assert "other.py" in names


def test_search_content_directory_scoping():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        base = Path(tmp_dir)
        (base / "root.txt").write_text("target")
        sub = base / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("target also")

        result = json.loads(wt.search_content(query="target", directory="sub"))
        assert result["matches_found"] == 1
        assert result["files"][0]["file"] == "sub/nested.txt"


def test_search_content_skips_excluded_dirs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        base = Path(tmp_dir)
        venv_pkg = base / ".venv" / "lib"
        venv_pkg.mkdir(parents=True)
        (venv_pkg / "hit.py").write_text("# TODO: vendor")
        (base / "real.py").write_text("# TODO: real work")

        result = json.loads(wt.search_content(query="TODO"))
        names = [m["file"] for m in result["files"]]
        assert result["matches_found"] == 1
        assert "real.py" in names
        assert not any(".venv" in f for f in names)


def test_search_content_empty_query():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        assert wt.search_content(query="").startswith("Error")


# ------------------------------------------------------------------
# write_file
# ------------------------------------------------------------------


def test_write_file_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        result = wt.write_file("nested/deep/file.txt", "hi")
        assert "Wrote" in result
        assert (Path(tmp_dir) / "nested" / "deep" / "file.txt").read_text() == "hi"


def test_write_file_no_overwrite():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        wt.write_file("a.txt", "first")
        result = wt.write_file("a.txt", "second", overwrite=False)
        assert result.startswith("Error")
        assert (Path(tmp_dir) / "a.txt").read_text() == "first"


# ------------------------------------------------------------------
# edit_file
# ------------------------------------------------------------------


def test_edit_file_replaces_unique_match():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("Hello, alpha. Goodbye, beta.")
        result = wt.edit_file("doc.md", old_str="alpha", new_str="ALPHA")
        assert "replaced 1 occurrence" in result
        assert (Path(tmp_dir) / "doc.md").read_text() == "Hello, ALPHA. Goodbye, beta."


def test_edit_file_rejects_zero_matches():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("Hello, alpha.")
        result = wt.edit_file("doc.md", old_str="missing", new_str="x")
        assert "not found" in result


def test_edit_file_rejects_multiple_matches():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("foo foo foo")
        result = wt.edit_file("doc.md", old_str="foo", new_str="bar")
        assert "matches 3 times" in result
        # File untouched.
        assert (Path(tmp_dir) / "doc.md").read_text() == "foo foo foo"


# ------------------------------------------------------------------
# delete_file
# ------------------------------------------------------------------


def test_delete_file_removes_file():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        target = Path(tmp_dir) / "byebye.txt"
        target.write_text("x")
        result = wt.delete_file("byebye.txt")
        assert "Deleted" in result
        assert not target.exists()


def test_delete_file_refuses_directory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        sub = Path(tmp_dir) / "subdir"
        sub.mkdir()
        result = wt.delete_file("subdir")
        assert result.startswith("Error")
        assert sub.exists()


# ------------------------------------------------------------------
# run_command
# ------------------------------------------------------------------


def test_run_command_success():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "file_a.txt").write_text("a")
        (Path(tmp_dir) / "file_b.txt").write_text("b")
        out = wt.run_command(["ls"])
        assert "file_a.txt" in out
        assert "file_b.txt" in out


def test_run_command_runs_in_base_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        out = wt.run_command(["pwd"])
        assert out.strip() == str(Path(tmp_dir).resolve())


def test_run_command_returns_error_on_nonzero_exit():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        out = wt.run_command(["ls", "definitely-does-not-exist-xyz"])
        assert out.startswith("Error")


# ------------------------------------------------------------------
# Async siblings — spot-check parity with sync
# ------------------------------------------------------------------


def test_async_read_file_matches_sync():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "a.txt").write_text("hi")
        sync_result = wt.read_file("a.txt")
        async_result = asyncio.run(wt.aread_file("a.txt"))
        assert sync_result == async_result == "hi"


def test_async_write_then_read():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)

        async def go():
            await wt.awrite_file("a.txt", "async write")
            return await wt.aread_file("a.txt")

        assert asyncio.run(go()) == "async write"


def test_async_run_command():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir)
        (Path(tmp_dir) / "marker.txt").write_text("x")
        out = asyncio.run(wt.arun_command(["ls"]))
        assert "marker.txt" in out


# ------------------------------------------------------------------
# Excludes config
# ------------------------------------------------------------------


def test_empty_exclude_patterns_opts_out():
    with tempfile.TemporaryDirectory() as tmp_dir:
        wt = WorkspaceTools(base_dir=tmp_dir, exclude_patterns=[])
        venv_pkg = Path(tmp_dir) / ".venv" / "lib"
        venv_pkg.mkdir(parents=True)
        (venv_pkg / "x.py").write_text("print('x')")
        result = json.loads(wt.list_files(pattern="**/*.py"))
        assert any(".venv" in f for f in result["files"])
