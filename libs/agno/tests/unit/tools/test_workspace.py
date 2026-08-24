import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

from agno.tools.workspace import Workspace

# All registered tool names (the descriptive names the LLM sees, after alias translation).
ALL_METHODS = [
    "read_file",
    "list_files",
    "search_content",
    "grep_content",
    "write_file",
    "edit_file",
    "move_file",
    "delete_file",
    "run_command",
]
READ_METHODS = ["read_file", "list_files", "search_content", "grep_content"]
WRITE_METHODS = ["write_file", "edit_file", "move_file", "delete_file", "run_command"]


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
    """allowed set, confirm=None → confirm defaults to [], not WRITE_TOOLS."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, allowed=["read"])
        assert list(ws.functions.keys()) == ["read_file"]
        assert ws.functions["read_file"].requires_confirmation is False


def test_only_confirm_set_makes_allowed_default_empty():
    """confirm set, allowed=None → allowed defaults to [], not READ_TOOLS."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, confirm=["write"])
        assert list(ws.functions.keys()) == ["write_file"]
        assert ws.functions["write_file"].requires_confirmation is True


def test_unknown_alias_in_allowed_raises():
    with pytest.raises(ValueError, match="Unknown alias"):
        Workspace(".", allowed=["read", "not_a_tool"])


def test_unknown_alias_in_confirm_raises():
    with pytest.raises(ValueError, match="Unknown alias"):
        Workspace(".", confirm=["bogus"])


def test_full_method_name_in_alias_list_raises():
    """Aliases are short; passing a full method name like 'read_file' should fail loud."""
    with pytest.raises(ValueError, match="Unknown alias"):
        Workspace(".", allowed=["read_file"])


def test_overlap_between_allowed_and_confirm_raises():
    with pytest.raises(ValueError, match="mutually exclusive"):
        Workspace(
            ".",
            allowed=["read", "write"],
            confirm=["write"],
        )


def test_empty_lists_in_both_registers_nothing():
    """Both empty lists → no methods registered (useful for tests)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, allowed=[], confirm=[])
        assert list(ws.functions.keys()) == []
        assert list(ws.async_functions.keys()) == []


def test_confirm_as_bool_raises_typeerror():
    """confirm=True is the natural typo — fail loud, not with a confusing alias error."""
    with pytest.raises(TypeError, match="`confirm` must be a list"):
        Workspace(".", confirm=True)


def test_allowed_as_string_raises_typeerror():
    """allowed='read' (not a list) → TypeError, not 4 'unknown alias' errors for r, e, a, d."""
    with pytest.raises(TypeError, match="`allowed` must be a list"):
        Workspace(".", allowed="read")


def test_custom_partition_works():
    """User-defined partition with both lists set."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(
            tmp_dir,
            allowed=["read"],
            confirm=["delete"],
        )
        assert sorted(ws.functions.keys()) == ["delete_file", "read_file"]
        assert ws.functions["read_file"].requires_confirmation is False
        assert ws.functions["delete_file"].requires_confirmation is True


def test_edit_instruction_only_added_when_edit_registered():
    """The 'always read_file before editing' nudge is gated on edit_file actually being available."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        read_only = Workspace(tmp_dir, allowed=Workspace.READ_TOOLS, confirm=[])
        assert "edit_file" not in read_only.functions
        assert read_only.instructions is None
        assert read_only.add_instructions is False

        with_edit_allowed = Workspace(tmp_dir, allowed=["read", "edit"], confirm=[])
        assert "edit_file" in with_edit_allowed.functions
        assert with_edit_allowed.instructions is not None
        assert "edit_file" in with_edit_allowed.instructions
        assert with_edit_allowed.add_instructions is True

        with_edit_confirm = Workspace(tmp_dir, allowed=["read"], confirm=["edit"])
        assert "edit_file" in with_edit_confirm.functions
        assert with_edit_confirm.instructions is not None
        assert with_edit_confirm.add_instructions is True


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
# Path escape protection (paths must resolve under root)
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
        # File outside the workspace root should not have been created.
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
# read_file (line-numbered output)
# ------------------------------------------------------------------


def test_read_file_returns_line_numbered_output():
    """read_file output is cat -n style (`{6d}\\t{line}`)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "hello.txt").write_text("alpha\nbeta\ngamma\n")
        out = ws.read_file("hello.txt")
        assert out == "     1\talpha\n     2\tbeta\n     3\tgamma"


def test_read_file_chunked_uses_actual_file_line_numbers():
    """Reading a chunk starting at line 2 should number it 2, not 1."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "lines.txt").write_text("a\nb\nc\nd\ne\n")
        out = ws.read_file("lines.txt", start_line=2, end_line=4)
        assert out == "     2\tb\n     3\tc\n     4\td"


def test_read_file_missing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        result = ws.read_file("does_not_exist.txt")
        assert result.startswith("Error: file not found")


def test_read_file_too_long_by_chars_hint_includes_search():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, max_file_length=10)
        (Path(tmp_dir) / "big.txt").write_text("a" * 100)
        result = ws.read_file("big.txt")
        assert "too long" in result
        assert "search_content" in result
        # Chunked read still works (and is line-numbered).
        out = ws.read_file("big.txt", start_line=1, end_line=1)
        assert out == "     1\t" + "a" * 100


def test_read_file_too_long_by_lines_hint_includes_search():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, max_file_lines=3)
        (Path(tmp_dir) / "many.txt").write_text("\n".join(str(i) for i in range(10)))
        result = ws.read_file("many.txt")
        assert "too long" in result
        assert "search_content" in result


# ------------------------------------------------------------------
# list_files (richer entries + recursive)
# ------------------------------------------------------------------


def test_list_files_returns_size_and_type():
    """Each entry is {path, type, size}; size is human-readable for files, null for dirs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "a.txt").write_text("hello")  # 5 bytes
        (Path(tmp_dir) / "subdir").mkdir()
        result = json.loads(ws.list_files())
        by_path = {e["path"]: e for e in result["files"]}
        assert by_path["a.txt"]["type"] == "file"
        assert by_path["a.txt"]["size"] == "5B"
        assert by_path["subdir"]["type"] == "dir"
        assert by_path["subdir"]["size"] is None


def test_list_files_with_glob_pattern():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "a.py").write_text("a")
        sub = base / "sub"
        sub.mkdir()
        (sub / "b.py").write_text("b")
        (base / "c.txt").write_text("c")

        result = json.loads(ws.list_files(pattern="**/*.py"))
        paths = sorted(e["path"] for e in result["files"])
        assert paths == ["a.py", "sub/b.py"]


def test_list_files_does_not_return_traversal_matches_outside_root():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        workspace_root = root / "workspace"
        outside_dir = root / "outside"
        workspace_root.mkdir()
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_text("outside secret")
        ws = Workspace(workspace_root)

        result = json.loads(ws.list_files(pattern="../outside/*.txt"))

        assert result["files"] == []


def test_list_files_skips_default_excludes():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "keep.txt").write_text("keep")
        (base / ".venv").mkdir()
        (base / ".venv" / "skip.txt").write_text("skip")

        result = json.loads(ws.list_files())
        paths = [e["path"] for e in result["files"]]
        assert "keep.txt" in paths
        assert ".venv" not in paths


def test_list_files_paths_are_relative():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "x.txt").write_text("x")
        result = json.loads(ws.list_files())
        for e in result["files"]:
            assert not e["path"].startswith("/")
            assert not e["path"].startswith(tmp_dir)


def test_list_files_recursive_walks_tree():
    """recursive=True returns nested entries up to max_depth."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "a.txt").write_text("a")
        (base / "src").mkdir()
        (base / "src" / "b.py").write_text("b")
        (base / "src" / "lib").mkdir()
        (base / "src" / "lib" / "c.py").write_text("c")

        result = json.loads(ws.list_files(recursive=True))
        paths = sorted(e["path"] for e in result["files"])
        assert "a.txt" in paths
        assert "src/b.py" in paths
        assert "src/lib/c.py" in paths
        assert result["recursive"] is True


def test_list_files_recursive_respects_max_depth():
    """max_depth=1 returns root children plus entries one level inside them."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "top.txt").write_text("a")
        (base / "lvl1").mkdir()
        (base / "lvl1" / "mid.txt").write_text("b")
        (base / "lvl1" / "lvl2").mkdir()
        (base / "lvl1" / "lvl2" / "deep.txt").write_text("c")

        result = json.loads(ws.list_files(recursive=True, max_depth=1))
        paths = sorted(e["path"] for e in result["files"])
        assert "top.txt" in paths
        assert "lvl1" in paths
        # Files at the boundary (depth 1) are shown.
        assert "lvl1/mid.txt" in paths
        assert "lvl1/lvl2" in paths
        # Files beyond max_depth are not shown.
        assert "lvl1/lvl2/deep.txt" not in paths


def test_list_files_recursive_max_depth_2_shows_two_levels():
    """max_depth=2 shows entries up to depth 2 but not depth 3."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "root.txt").write_text("a")
        (base / "d1").mkdir()
        (base / "d1" / "f1.txt").write_text("b")
        (base / "d1" / "d2").mkdir()
        (base / "d1" / "d2" / "f2.txt").write_text("c")
        (base / "d1" / "d2" / "d3").mkdir()
        (base / "d1" / "d2" / "d3" / "f3.txt").write_text("d")

        result = json.loads(ws.list_files(recursive=True, max_depth=2))
        paths = sorted(e["path"] for e in result["files"])
        assert "root.txt" in paths
        assert "d1" in paths
        assert "d1/f1.txt" in paths
        assert "d1/d2" in paths
        assert "d1/d2/f2.txt" in paths
        assert "d1/d2/d3" in paths
        # depth 3 is beyond max_depth=2
        assert "d1/d2/d3/f3.txt" not in paths


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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_search_content_skips_symlink_targets_outside_root():
    """Test that search_content skips symlink targets outside root."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        workspace_root = root / "workspace"
        outside_dir = root / "outside"
        workspace_root.mkdir()
        outside_dir.mkdir()
        secret = outside_dir / "secret.txt"
        secret.write_text("outside needle")
        try:
            (workspace_root / "linked-secret.txt").symlink_to(secret)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")
        ws = Workspace(workspace_root)

        result = json.loads(ws.search_content(query="needle"))

        assert result["matches_found"] == 0
        assert result["files"] == []


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


def test_search_content_skips_agent_scratch_and_plural_venvs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "real.py").write_text("# TODO: real work")
        (base / ".context").mkdir()
        (base / ".context" / "notes.py").write_text("# TODO: scratch")
        venvs_pkg = base / ".venvs" / "demo" / "lib"
        venvs_pkg.mkdir(parents=True)
        (venvs_pkg / "installed.py").write_text("# TODO: dependency")

        result = json.loads(ws.search_content(query="TODO", limit=10))
        names = [m["file"] for m in result["files"]]
        assert result["matches_found"] == 1
        assert names == ["real.py"]


def test_search_content_empty_query():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        assert ws.search_content(query="").startswith("Error")


# ------------------------------------------------------------------
# grep_content (regex with line numbers)
# ------------------------------------------------------------------


def test_grep_content_basic():
    """grep_content returns path:line:text format."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "code.py").write_text("def foo():\n    pass\n\ndef bar():\n    return 1")

        result = ws.grep_content(pattern="def ")
        assert "code.py:1:def foo():" in result
        assert "code.py:4:def bar():" in result


def test_grep_content_regex():
    """grep_content supports regex patterns."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "code.py").write_text("async def run():\n    pass\ndef sync_run():\n    pass")

        # Match only async def
        result = ws.grep_content(pattern=r"async\s+def")
        assert "code.py:1:async def run():" in result
        assert "sync_run" not in result


def test_grep_content_ignore_case():
    """grep_content ignore_case flag works."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "doc.md").write_text("TODO: fix this\nTodo: later\ntodo: now")

        result = ws.grep_content(pattern="TODO", ignore_case=True)
        assert result.count("doc.md:") == 3

        result = ws.grep_content(pattern="TODO", ignore_case=False)
        assert result.count("doc.md:") == 1


def test_grep_content_context_lines():
    """grep_content context_lines shows surrounding lines."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "code.py").write_text("# header\ndef target():\n    pass\n# footer")

        result = ws.grep_content(pattern="def target", context_lines=1)
        assert "code.py:1:# header" in result
        assert "code.py:2:def target():" in result
        assert "code.py:3:    pass" in result


def test_grep_content_files_only():
    """grep_content files_only=True returns only file names."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "a.py").write_text("def foo(): pass")
        (base / "b.py").write_text("def bar(): pass")
        (base / "c.txt").write_text("nothing special here")

        result = ws.grep_content(pattern="def ", files_only=True)
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result
        assert "(2 files)" in result


def test_grep_content_respects_limit():
    """grep_content respects the limit parameter."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "code.py").write_text("\n".join(f"line{i}" for i in range(100)))

        result = ws.grep_content(pattern="line", limit=5)
        assert "(showing 5 matches, limit=5)" in result


def test_grep_content_invalid_regex():
    """grep_content returns error for invalid regex."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        result = ws.grep_content(pattern="[invalid")
        assert result.startswith("Error: invalid regex")


def test_grep_content_no_matches():
    """grep_content returns message when no matches."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "file.py").write_text("nothing here")

        result = ws.grep_content(pattern="NOTFOUND")
        assert "No matches for pattern" in result


def test_grep_content_skips_excluded():
    """grep_content skips excluded directories."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "real.py").write_text("def real(): pass")
        (base / ".venv").mkdir()
        (base / ".venv" / "hidden.py").write_text("def hidden(): pass")

        result = ws.grep_content(pattern="def ")
        assert "real.py" in result
        assert ".venv" not in result


def test_agrep_content_async():
    """agrep_content async variant works."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        base = Path(tmp_dir)
        (base / "code.py").write_text("def foo(): pass")

        result = asyncio.run(ws.agrep_content(pattern="def "))
        assert "code.py:1:def foo():" in result


# ------------------------------------------------------------------
# write_file (atomic)
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


def test_write_file_atomic_no_tmp_leftover():
    """A successful write should not leave a .tmp file behind."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        ws.write_file("a.txt", "content")
        assert (Path(tmp_dir) / "a.txt").read_text() == "content"
        assert not (Path(tmp_dir) / "a.txt.tmp").exists()


# ------------------------------------------------------------------
# edit_file (replace_all)
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


def test_edit_file_rejects_multiple_matches_default():
    """Without replace_all, multiple matches → error mentioning replace_all."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("foo foo foo")
        result = ws.edit_file("doc.md", old_str="foo", new_str="bar")
        assert "matches 3 times" in result
        assert "replace_all" in result
        # File untouched.
        assert (Path(tmp_dir) / "doc.md").read_text() == "foo foo foo"


def test_edit_file_replace_all_replaces_every_occurrence():
    """replace_all=True replaces all occurrences and reports the count."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("foo bar foo baz foo")
        result = ws.edit_file("doc.md", old_str="foo", new_str="QUX", replace_all=True)
        assert "replaced 3 occurrences" in result
        assert (Path(tmp_dir) / "doc.md").read_text() == "QUX bar QUX baz QUX"


def test_edit_file_empty_old_str_rejected():
    """Empty old_str must be rejected — str.replace('', x) corrupts the file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("Hello")
        result = ws.edit_file("doc.md", old_str="", new_str="X")
        assert result.startswith("Error: old_str cannot be empty")
        # File must be untouched.
        assert (Path(tmp_dir) / "doc.md").read_text() == "Hello"


def test_edit_file_empty_old_str_with_replace_all_rejected():
    """Empty old_str with replace_all=True must also be rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "doc.md").write_text("Hello")
        result = ws.edit_file("doc.md", old_str="", new_str="X", replace_all=True)
        assert result.startswith("Error: old_str cannot be empty")
        assert (Path(tmp_dir) / "doc.md").read_text() == "Hello"


# ------------------------------------------------------------------
# move_file
# ------------------------------------------------------------------


def test_move_file_renames_within_workspace():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "old.txt").write_text("hi")
        result = ws.move_file("old.txt", "new.txt")
        assert "Moved old.txt -> new.txt" in result
        assert not (Path(tmp_dir) / "old.txt").exists()
        assert (Path(tmp_dir) / "new.txt").read_text() == "hi"


def test_move_file_creates_dst_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "src.txt").write_text("hi")
        result = ws.move_file("src.txt", "nested/deep/dst.txt")
        assert "Moved" in result
        assert (Path(tmp_dir) / "nested" / "deep" / "dst.txt").read_text() == "hi"


def test_move_file_refuses_existing_dst_without_overwrite():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "a.txt").write_text("a")
        (Path(tmp_dir) / "b.txt").write_text("b")
        result = ws.move_file("a.txt", "b.txt")
        assert result.startswith("Error: dst exists")
        # Both still present, untouched.
        assert (Path(tmp_dir) / "a.txt").read_text() == "a"
        assert (Path(tmp_dir) / "b.txt").read_text() == "b"


def test_move_file_overwrite_true_replaces_dst():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "a.txt").write_text("source")
        (Path(tmp_dir) / "b.txt").write_text("target")
        result = ws.move_file("a.txt", "b.txt", overwrite=True)
        assert "Moved" in result
        assert not (Path(tmp_dir) / "a.txt").exists()
        assert (Path(tmp_dir) / "b.txt").read_text() == "source"


def test_move_file_path_escape_blocked_on_src():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        result = ws.move_file("../outside.txt", "inside.txt")
        assert result.startswith("Error: src escapes")


def test_move_file_path_escape_blocked_on_dst():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "a.txt").write_text("hi")
        result = ws.move_file("a.txt", "../escape.txt")
        assert result.startswith("Error: dst escapes")


def test_move_file_missing_src():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        result = ws.move_file("does_not_exist.txt", "wherever.txt")
        assert "Error: src not found" in result


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
# require_read_before_write
# ------------------------------------------------------------------


def test_require_read_before_write_blocks_unread_write():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, require_read_before_write=True)
        (Path(tmp_dir) / "existing.txt").write_text("original")
        result = ws.write_file("existing.txt", "tampered")
        assert "require_read_before_write" in result
        # File untouched.
        assert (Path(tmp_dir) / "existing.txt").read_text() == "original"


def test_require_read_before_write_allows_after_read():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, require_read_before_write=True)
        (Path(tmp_dir) / "existing.txt").write_text("original")
        ws.read_file("existing.txt")
        result = ws.write_file("existing.txt", "updated")
        assert "Wrote" in result
        assert (Path(tmp_dir) / "existing.txt").read_text() == "updated"


def test_require_read_before_write_allows_new_file():
    """Creating a new file doesn't require a prior read (nothing to hallucinate)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, require_read_before_write=True)
        result = ws.write_file("brand_new.txt", "content")
        assert "Wrote" in result
        assert (Path(tmp_dir) / "brand_new.txt").read_text() == "content"


def test_require_read_before_write_blocks_unread_edit():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, require_read_before_write=True)
        (Path(tmp_dir) / "doc.md").write_text("Hello, world.")
        result = ws.edit_file("doc.md", old_str="world", new_str="Agno")
        assert "require_read_before_write" in result
        assert (Path(tmp_dir) / "doc.md").read_text() == "Hello, world."


def test_require_read_before_write_blocks_unread_delete():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir, require_read_before_write=True)
        (Path(tmp_dir) / "trash.txt").write_text("anything")
        result = ws.delete_file("trash.txt")
        assert "require_read_before_write" in result
        assert (Path(tmp_dir) / "trash.txt").exists()


# ------------------------------------------------------------------
# run_command (ANSI strip)
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


def test_run_command_strips_ansi_color_codes():
    """Color codes from CLI output should be stripped before tailing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        # printf interprets the \x1b escape and produces a literal red "RED" plus reset.
        out = ws.run_command(["printf", "\x1b[31mRED\x1b[0m\n"])
        assert out == "RED"
        assert "\x1b" not in out


def test_run_command_timeout_kills_long_running_process():
    """A command exceeding the timeout should be killed and return an error."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        out = ws.run_command(["sleep", "30"], timeout=1)
        assert "timed out" in out
        assert "1 seconds" in out


def test_run_command_timeout_default_allows_fast_commands():
    """Fast commands should complete normally under the default timeout."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        out = ws.run_command(["echo", "hello"])
        assert out.strip() == "hello"


def test_async_run_command_timeout():
    """Async variant should also respect timeout."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        out = asyncio.run(ws.arun_command(["sleep", "30"], timeout=1))
        assert "timed out" in out
        assert "1 seconds" in out


# ------------------------------------------------------------------
# Async siblings — spot-check parity with sync
# ------------------------------------------------------------------


def test_async_read_file_matches_sync():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "a.txt").write_text("hi")
        sync_result = ws.read_file("a.txt")
        async_result = asyncio.run(ws.aread_file("a.txt"))
        assert sync_result == async_result == "     1\thi"


def test_async_write_then_read():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)

        async def go():
            await ws.awrite_file("a.txt", "async write")
            return await ws.aread_file("a.txt")

        assert asyncio.run(go()) == "     1\tasync write"


def test_async_run_command():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "marker.txt").write_text("x")
        out = asyncio.run(ws.arun_command(["ls"]))
        assert "marker.txt" in out


def test_async_move_file():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        (Path(tmp_dir) / "src.txt").write_text("x")
        out = asyncio.run(ws.amove_file("src.txt", "dst.txt"))
        assert "Moved" in out
        assert (Path(tmp_dir) / "dst.txt").read_text() == "x"


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
        paths = [e["path"] for e in result["files"]]
        assert any(".venv" in p for p in paths)


# ------------------------------------------------------------------
# Exclude enforcement: excluded paths are refused by name, not just hidden
# ------------------------------------------------------------------


def _secrets_repo(tmp_dir: str) -> Path:
    """A fixture repo with a live-looking .env, a local.env, a .git dir, and one ordinary file."""
    base = Path(tmp_dir).resolve()
    (base / ".env").write_text("OPENAI_API_KEY=sk-live-secret\n")
    (base / "local.env").write_text("OPENAI_API_KEY=sk-local-secret\n")
    (base / ".git").mkdir()
    (base / ".git" / "config").write_text("[core]\n")
    (base / "app.py").write_text("print('app')\n")
    return base


def _fs_is_case_insensitive(base: Path) -> bool:
    probe = base / "CaseProbe.txt"
    probe.write_text("x")
    try:
        return (base / "caseprobe.TXT").exists()
    finally:
        probe.unlink()


def test_read_file_refuses_excluded_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir)
        out = ws.read_file(".env")
        assert out == "Error: path is excluded from this workspace: .env"
        assert "sk-live-secret" not in out
        assert ws.read_file(".git/config") == "Error: path is excluded from this workspace: .git/config"
        # Unexcluded files still read normally.
        assert "print('app')" in ws.read_file("app.py")


def test_default_workspace_cannot_read_env_in_fixture_repo():
    """Regression: the default configuration must not return a repo's .env."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir)
        assert "OPENAI_API_KEY" not in ws.read_file(".env")
        assert "OPENAI_API_KEY" not in ws.read_file("./.env")
        assert "OPENAI_API_KEY" not in ws.read_file("app.py/../.env")
        listed = [e["path"] for e in json.loads(ws.list_files())["files"]]
        assert ".env" not in listed
        assert "local.env" not in listed
        assert json.loads(ws.search_content("OPENAI_API_KEY"))["matches_found"] == 0
        assert "sk-local-secret" not in ws.read_file("local.env")
        # The file itself is untouched.
        assert (base / ".env").read_text() == "OPENAI_API_KEY=sk-live-secret\n"


def test_read_file_refusal_does_not_reveal_existence():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Workspace(tmp_dir)
        missing = ws.read_file(".env")
        (Path(tmp_dir) / ".env").write_text("X=1")
        present = ws.read_file(".env")
        assert missing == present == "Error: path is excluded from this workspace: .env"


def test_read_file_refused_path_is_not_marked_as_read():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, require_read_before_write=True)
        ws.read_file(".env")
        assert (base / ".env") not in ws._read_paths


def test_write_file_refuses_excluded_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        assert ws.write_file(".env", "X=1") == "Error: path is excluded from this workspace: .env"
        assert (base / ".env").read_text() == "OPENAI_API_KEY=sk-live-secret\n"
        assert ws.write_file(".env.local", "X=1") == "Error: path is excluded from this workspace: .env.local"
        assert not (base / ".env.local").exists()
        assert ws.write_file(".git/hooks/pre-commit", "#!/bin/sh") == (
            "Error: path is excluded from this workspace: .git/hooks/pre-commit"
        )
        assert not (base / ".git" / "hooks").exists()


def test_edit_file_refuses_excluded_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        assert ws.edit_file(".env", "secret", "leak") == "Error: path is excluded from this workspace: .env"
        assert (base / ".env").read_text() == "OPENAI_API_KEY=sk-live-secret\n"


def test_delete_file_refuses_excluded_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        assert ws.delete_file(".env") == "Error: path is excluded from this workspace: .env"
        assert (base / ".env").exists()


def test_move_file_refuses_excluded_src():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        assert ws.move_file(".env", "env.txt") == "Error: src is excluded from this workspace: .env"
        assert (base / ".env").exists()
        assert not (base / "env.txt").exists()
        # The laundered name never appears in listings.
        assert "env.txt" not in [e["path"] for e in json.loads(ws.list_files())["files"]]


def test_move_file_refuses_excluded_dst():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        assert ws.move_file("app.py", ".env.bak") == "Error: dst is excluded from this workspace: .env.bak"
        assert (base / "app.py").exists()
        assert not (base / ".env.bak").exists()
        assert ws.move_file("app.py", "build/app.py") == "Error: dst is excluded from this workspace: build/app.py"
        assert not (base / "build").exists()


def test_move_file_unexcluded_to_unexcluded_still_works():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        assert ws.move_file("app.py", "src/main.py") == "Moved app.py -> src/main.py"
        assert (base / "src" / "main.py").read_text() == "print('app')\n"


def test_list_files_refuses_excluded_directory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir)
        assert ws.list_files(".git") == "Error: directory is excluded from this workspace: .git"
        assert ws.list_files(".git", recursive=True) == "Error: directory is excluded from this workspace: .git"


def test_search_content_refuses_excluded_directory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir)
        assert ws.search_content("core", directory=".git") == "Error: directory is excluded from this workspace: .git"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_excluded_path_behind_symlink_is_refused():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        (base / "link.txt").symlink_to(base / ".env")
        out = ws.read_file("link.txt")
        assert out == "Error: path is excluded from this workspace: link.txt"
        assert "sk-live-secret" not in out
        assert ws.write_file("link.txt", "X=1") == "Error: path is excluded from this workspace: link.txt"
        assert ws.edit_file("link.txt", "secret", "x") == "Error: path is excluded from this workspace: link.txt"
        assert ws.move_file("link.txt", "copy.txt") == "Error: src is excluded from this workspace: link.txt"
        assert (
            ws.move_file("app.py", "link.txt", overwrite=True) == "Error: dst is excluded from this workspace: link.txt"
        )
        assert ws.delete_file("link.txt") == "Error: path is excluded from this workspace: link.txt"
        assert (base / ".env").read_text() == "OPENAI_API_KEY=sk-live-secret\n"
        assert (base / "app.py").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_symlink_aliases_are_hidden_from_listing_and_search():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        (base / "link.txt").symlink_to(base / ".env")
        (base / "gl").symlink_to(base / ".git")
        ws = Workspace(tmp_dir)
        listed = [e["path"] for e in json.loads(ws.list_files())["files"]]
        assert "link.txt" not in listed
        assert "gl" not in listed
        assert [e["path"] for e in json.loads(ws.list_files(recursive=True))["files"]] == ["app.py"]
        assert json.loads(ws.list_files(pattern="gl/*"))["files"] == []
        assert json.loads(ws.list_files(pattern="*.txt"))["files"] == []
        assert json.loads(ws.search_content("OPENAI_API_KEY"))["matches_found"] == 0
        assert ws.read_file("gl/config") == "Error: path is excluded from this workspace: gl/config"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_excluded_name_linking_to_unexcluded_file_is_refused():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        (base / ".env.link").symlink_to(base / "app.py")
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        assert ws.read_file(".env.link") == "Error: path is excluded from this workspace: .env.link"
        assert ws.write_file(".env.link", "Z") == "Error: path is excluded from this workspace: .env.link"
        assert (base / "app.py").read_text() == "print('app')\n"
        assert ".env.link" not in [e["path"] for e in json.loads(ws.list_files())["files"]]


def test_case_variant_never_leaks_on_any_filesystem():
    """A case variant never reads, edits, moves, or deletes the excluded file.

    On a case-insensitive filesystem the variant is refused; on a case-sensitive one it
    names a different, absent file.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        (base / "sub").mkdir()
        (base / "sub" / ".env").write_text("SUB_SECRET=1\n")
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        for typed in (".ENV", ".Env", ".GIT/config", "sub/.ENV", "SUB/.env", "LOCAL.ENV"):
            out = ws.read_file(typed)
            assert out.startswith("Error: "), typed
            assert "secret" not in out.lower() and "[core]" not in out, typed
        assert ws.edit_file(".ENV", "secret", "x").startswith("Error: ")
        assert ws.move_file(".ENV", "env.txt").startswith("Error: ")
        assert ws.delete_file(".ENV").startswith("Error: ")
        assert ws.list_files(".GIT").startswith("Error: ")
        assert ws.search_content("core", directory=".GIT").startswith("Error: ")
        if _fs_is_case_insensitive(base):
            assert ws.write_file(".ENV", "PWNED=1") == "Error: path is excluded from this workspace: .ENV"
        else:
            assert ws.write_file(".ENV", "PWNED=1") == "Wrote 7 chars to .ENV"
            assert (base / ".ENV").read_text() == "PWNED=1"
        assert (base / ".env").read_text() == "OPENAI_API_KEY=sk-live-secret\n"
        assert (base / "sub" / ".env").read_text() == "SUB_SECRET=1\n"
        assert not (base / "env.txt").exists()


def test_case_variant_returns_exclusion_error_on_case_insensitive_fs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        if not _fs_is_case_insensitive(base):
            pytest.skip("needs a case-insensitive filesystem")
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)
        assert ws.read_file(".ENV") == "Error: path is excluded from this workspace: .ENV"
        assert ws.read_file(".GIT/config") == "Error: path is excluded from this workspace: .GIT/config"
        assert ws.write_file(".ENV", "PWNED=1") == "Error: path is excluded from this workspace: .ENV"
        assert ws.move_file(".ENV", "env.txt") == "Error: src is excluded from this workspace: .ENV"
        assert ws.list_files(".GIT") == "Error: directory is excluded from this workspace: .GIT"
        # A file stored in upper case is the same name to this filesystem.
        (base / "BUILD").write_text("bazel")
        assert ws.read_file("BUILD") == "Error: path is excluded from this workspace: BUILD"
        assert "BUILD" not in [e["path"] for e in json.loads(ws.list_files())["files"]]
        # allow_paths entries match the stored file whatever case the caller types.
        ws2 = Workspace(tmp_dir, allow_paths=["local.env"])
        assert "sk-local-secret" in ws2.read_file("LOCAL.ENV")


def test_case_sensitive_fs_matches_patterns_exactly():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        if _fs_is_case_insensitive(base):
            pytest.skip("needs a case-sensitive filesystem")
        (base / "BUILD").write_text("bazel")
        ws = Workspace(tmp_dir)
        assert "bazel" in ws.read_file("BUILD")
        assert "BUILD" in [e["path"] for e in json.loads(ws.list_files())["files"]]
        assert ws.read_file(".ENV") == "Error: file not found: .ENV"


def test_case_folding_when_root_is_detected_case_insensitive(monkeypatch):
    """Pins the folded match on every platform by forcing the filesystem probe."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        (base / "BUILD").write_text("bazel")
        (base / "infra").mkdir()
        (base / "infra" / ".env").write_text("INFRA=1")
        monkeypatch.setattr("agno.tools.workspace._is_case_insensitive_fs", lambda root: True)
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS, allow_paths=["infra/.env"])
        assert ws.read_file(".ENV") == "Error: path is excluded from this workspace: .ENV"
        assert ws.write_file(".ENV", "PWNED=1") == "Error: path is excluded from this workspace: .ENV"
        assert ws.list_files(".GIT") == "Error: directory is excluded from this workspace: .GIT"
        assert ws.read_file("BUILD") == "Error: path is excluded from this workspace: BUILD"
        assert "BUILD" not in [e["path"] for e in json.loads(ws.list_files())["files"]]
        # allow_paths compare case-insensitively too: the variant passes the boundary
        # (and reads the file where the filesystem really is case-insensitive).
        out = ws.read_file("INFRA/.ENV")
        assert not out.startswith("Error: path is excluded")
        assert "INFRA=1" in out or out == "Error: file not found: INFRA/.ENV"
        assert "INFRA=1" in ws.read_file("infra/.env")


def test_case_folding_off_when_root_is_detected_case_sensitive(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        (base / "BUILD").write_text("bazel")
        monkeypatch.setattr("agno.tools.workspace._is_case_insensitive_fs", lambda root: False)
        ws = Workspace(tmp_dir)
        assert "bazel" in ws.read_file("BUILD")
        assert ws.read_file(".env") == "Error: path is excluded from this workspace: .env"


# ------------------------------------------------------------------
# allow_paths: named exceptions to the exclude boundary
# ------------------------------------------------------------------


def test_allow_paths_restores_access_for_named_path_only():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS, allow_paths=[".env.example"])
        assert ws.write_file(".env.example", "OPENAI_API_KEY=\n") == "Wrote 16 chars to .env.example"
        assert (base / ".env.example").read_text() == "OPENAI_API_KEY=\n"
        assert "OPENAI_API_KEY=" in ws.read_file(".env.example")
        # .env matches the same pattern and stays refused.
        assert ws.read_file(".env") == "Error: path is excluded from this workspace: .env"
        assert ws.read_file(".git/config") == "Error: path is excluded from this workspace: .git/config"


def test_allow_paths_entry_is_visible_in_listing_and_search():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _secrets_repo(tmp_dir)
        # local.env matches the default "*.env" pattern and has a searchable text suffix.
        ws = Workspace(tmp_dir, allow_paths=["local.env"])
        paths = [e["path"] for e in json.loads(ws.list_files())["files"]]
        assert "local.env" in paths
        assert ".env" not in paths
        hits = json.loads(ws.search_content("OPENAI_API_KEY"))
        assert [h["file"] for h in hits["files"]] == ["local.env"]


def test_allow_paths_directory_covers_children():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        (base / "build").mkdir()
        (base / "build" / "index.html").write_text("<html>")
        (base / "dist").mkdir()
        (base / "dist" / "bundle.js").write_text("x")
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS, allow_paths=["build"])
        assert "<html>" in ws.read_file("build/index.html")
        assert ws.write_file("build/new.txt", "n") == "Wrote 1 chars to build/new.txt"
        paths = [e["path"] for e in json.loads(ws.list_files("build"))["files"]]
        assert "build/index.html" in paths
        assert ws.read_file("dist/bundle.js") == "Error: path is excluded from this workspace: dist/bundle.js"


def test_allow_paths_entry_must_stay_inside_root():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(ValueError, match="allow_paths"):
            Workspace(tmp_dir, allow_paths=["../outside"])
        with pytest.raises(ValueError, match="allow_paths"):
            Workspace(tmp_dir, allow_paths=[""])


def test_allow_paths_rejects_non_list():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(TypeError, match="allow_paths"):
            Workspace(tmp_dir, allow_paths=".env.example")  # type: ignore[arg-type]


def test_allow_paths_entry_naming_root_is_rejected():
    with tempfile.TemporaryDirectory() as tmp_dir:
        for entry in (".", "./", "sub/.."):
            with pytest.raises(ValueError, match="names the workspace root"):
                Workspace(tmp_dir, allow_paths=[entry])


def test_allow_paths_directory_entry_keeps_patterns_beneath_it():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        (base / "infra").mkdir()
        (base / "infra" / "main.tf").write_text("tf")
        (base / "infra" / ".env").write_text("INFRA_KEY=sk-infra\n")
        (base / "infra" / "node_modules").mkdir()
        (base / "infra" / "node_modules" / "m.js").write_text("m")
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS, allow_paths=["infra"])
        assert "tf" in ws.read_file("infra/main.tf")
        assert ws.read_file("infra/.env") == "Error: path is excluded from this workspace: infra/.env"
        assert ws.read_file("infra/node_modules/m.js") == (
            "Error: path is excluded from this workspace: infra/node_modules/m.js"
        )
        assert [e["path"] for e in json.loads(ws.list_files("infra"))["files"]] == ["infra/main.tf"]
        # The nested file can be named explicitly.
        ws2 = Workspace(tmp_dir, allow_paths=["infra/.env"])
        assert "INFRA_KEY" in ws2.read_file("infra/.env")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks require admin on Windows")
def test_allow_paths_entry_that_is_a_symlink_works_as_written_and_resolved():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        (base / "out").mkdir()
        (base / "out" / "index.html").write_text("<html>")
        (base / "build").symlink_to(base / "out")
        ws = Workspace(tmp_dir, allow_paths=["build"])
        assert "<html>" in ws.read_file("build/index.html")
        assert "<html>" in ws.read_file("out/index.html")
        listed = [e["path"] for e in json.loads(ws.list_files())["files"]]
        assert "build" in listed and "out" in listed
        # An allowed file reached through a symlinked parent directory is allowed.
        (base / "infra").mkdir()
        (base / "infra" / ".env").write_text("INFRA=1")
        (base / "lnk").symlink_to(base / "infra")
        ws2 = Workspace(tmp_dir, allow_paths=["infra/.env"])
        assert "INFRA=1" in ws2.read_file("lnk/.env")
        assert ws2.read_file("lnk/../.env") == "Error: path is excluded from this workspace: lnk/../.env"


def test_allowed_target_reached_through_dot_dot_is_allowed():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = _secrets_repo(tmp_dir)
        (base / "sub").mkdir()
        (base / ".env.example").write_text("OPENAI_API_KEY=\n")
        ws = Workspace(tmp_dir, allow_paths=[".env.example"])
        assert "OPENAI_API_KEY=" in ws.read_file("sub/../.env.example")
        assert "print('app')" in ws.read_file("build/../app.py")
        assert ws.read_file("sub/../.env") == "Error: path is excluded from this workspace: sub/../.env"


def test_allow_paths_accepts_path_objects():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, allow_paths=[Path("local.env")])  # type: ignore[list-item]
        assert "sk-local-secret" in ws.read_file("local.env")
        with pytest.raises(ValueError, match="allow_paths"):
            Workspace(tmp_dir, allow_paths=[42])  # type: ignore[list-item]


def test_exclude_patterns_generator_is_materialized():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir, exclude_patterns=(p for p in [".env*"]))  # type: ignore[arg-type]
        assert ws.exclude_patterns == [".env*"]
        assert ws.read_file(".env") == "Error: path is excluded from this workspace: .env"


def test_allow_paths_is_read_live():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _secrets_repo(tmp_dir)
        ws = Workspace(tmp_dir)
        assert ws.read_file("local.env") == "Error: path is excluded from this workspace: local.env"
        ws.allow_paths.append("local.env")
        assert "sk-local-secret" in ws.read_file("local.env")
        ws.allow_paths = []
        assert ws.read_file("local.env") == "Error: path is excluded from this workspace: local.env"


def test_exclude_pattern_with_path_separator_is_rejected():
    with tempfile.TemporaryDirectory() as tmp_dir:
        for pattern in ("dist/", "config/secrets.yaml", "**/secrets.yaml", "config\\secrets.yaml"):
            with pytest.raises(ValueError, match="path separator"):
                Workspace(tmp_dir, exclude_patterns=[pattern])


def test_allow_paths_does_not_cover_siblings_or_parents():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        (base / ".venv" / "lib").mkdir(parents=True)
        (base / ".venv" / "lib" / "ok.py").write_text("ok")
        (base / ".venv" / "pyvenv.cfg").write_text("home = x")
        ws = Workspace(tmp_dir, allow_paths=[".venv/lib/ok.py"])
        assert "ok" in ws.read_file(".venv/lib/ok.py")
        assert ws.read_file(".venv/pyvenv.cfg") == "Error: path is excluded from this workspace: .venv/pyvenv.cfg"
        assert ws.list_files(".venv") == "Error: directory is excluded from this workspace: .venv"


# ------------------------------------------------------------------
# Default credential excludes: the default list is the access boundary
# ------------------------------------------------------------------

# Files a real repository or home directory conventionally keeps credentials in.
CREDENTIAL_PATHS = [
    "id_rsa",
    "id_rsa.pub",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "server.pem",
    "private.key",
    "server.crt",
    "ca.cer",
    "ca.der",
    "signing.p8",
    "cert.p12",
    "cert.pfx",
    "keystore.jks",
    "store.jceks",
    "my.keystore",
    "private.gpg",
    "server.ppk",
    "vault.kdbx",
    "krb5.keytab",
    "known_hosts",
    "authorized_keys",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "_netrc",
    ".git-credentials",
    ".dockercfg",
    ".pgpass",
    ".my.cnf",
    ".boto",
    ".s3cfg",
    "rclone.conf",
    "kubeconfig",
    ".htpasswd",
    "htpasswd",
    "credentials.json",
    "credentials.yaml",
    "credentials.yml",
    "credentials.ini",
    "credentials.cfg",
    "credentials.csv",
    "credentials.toml",
    "credentials.xml",
    "credentials.properties",
    "aws-credentials.json",
    "db_credentials.yaml",
    "application_default_credentials.json",
    "secret.json",
    "secret.yaml",
    "secret.yml",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.ini",
    "secrets.cfg",
    "secrets.toml",
    "secrets.properties",
    "app-secrets.yaml",
    "token.json",
    "tokens.json",
    "accessKeys.csv",
    "azureProfile.json",
    "service_account.json",
    "service_account_key.json",
    "serviceAccount.json",
    "serviceAccountKey.json",
    "service-account.json",
    "gcp-service-account.json",
    "terraform.tfvars",
    "prod.tfvars.json",
    ".ssh/id_ed25519",
    ".aws/credentials",
    ".gnupg/secring.gpg",
    ".kube/config",
    ".docker/config.json",
    ".azure/azureProfile.json",
    ".m2/settings.xml",
    ".cargo/credentials.toml",
    ".composer/auth.json",
    "config/credentials.json",
]

# Ordinary source and documentation. A workspace toolkit exists to read these, and the
# obvious `credentials.*` / `secrets.*` spelling of the patterns above would refuse them.
SOURCE_PATHS = [
    "credentials.py",
    "credentials.ts",
    "credentials.go",
    "credentials.rs",
    "credentials.md",
    "credentials.test.js",
    "credentials_test.go",
    "secrets.py",
    "secrets.ts",
    "secrets.tf",
    "secrets.md",
    "secrets_manager.py",
    "aws-credentials.md",
    "app/auth/credentials.py",
    "docs/secrets.md",
    "src/credentials/loader.py",
    "lib/credentials/__init__.py",
    "keystore.py",
    "keystore/index.ts",
    "key.py",
    "keys.py",
    "cert.ts",
    "pem.md",
    "crt.go",
    "docs/keys.md",
    "terraform.tfvars.example",
]

# Committed env templates: placeholders by definition, and where a repo documents its
# environment variables.
ENV_TEMPLATES = [
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
    "example.env",
    "sample.env",
    "template.env",
    "dist.env",
    "env.example",
    "packages/api/.env.example",
]

ENV_SECRETS = [".env", ".env.local", ".env.production", ".env.development", ".env.vault", ".envrc"]


def _write(base: Path, rel: str, content: str) -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@pytest.mark.parametrize("rel", CREDENTIAL_PATHS)
def test_default_excludes_block_conventional_credential_files(rel):
    """Since exclusion refuses reads, the default list is the control. Content must not
    reach the tool result through any of the three read surfaces."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, rel, "ZQMARKER-SECRET\n")
        ws = Workspace(tmp_dir)

        assert ws.read_file(rel) == f"Error: path is excluded from this workspace: {rel}"
        assert "ZQMARKER-SECRET" not in ws.read_file(rel)
        listed = [e["path"] for e in json.loads(ws.list_files(recursive=True))["files"]]
        assert rel not in listed
        found = json.loads(ws.search_content("ZQMARKER-SECRET"))
        assert found["matches_found"] == 0


@pytest.mark.parametrize("rel", SOURCE_PATHS)
def test_default_excludes_do_not_block_source_files(rel):
    """The trap: `credentials.*` and `secrets.*` are the obvious spelling and would
    refuse every one of these. A bare `credentials` entry would take the two package
    directories with it."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, rel, "ZQMARKER-SOURCE\n")
        ws = Workspace(tmp_dir)

        assert "ZQMARKER-SOURCE" in ws.read_file(rel)
        listed = [e["path"] for e in json.loads(ws.list_files(recursive=True))["files"]]
        assert rel in listed


def test_credential_refusal_covers_every_path_spelling():
    """A refusal that only knows the bare name is not a boundary."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, "credentials.json", "ZQMARKER-SECRET\n")
        _write(base, "src/app.py", "print('app')\n")
        ws = Workspace(tmp_dir, allowed=Workspace.ALL_TOOLS)

        for spelling in (
            "credentials.json",
            "./credentials.json",
            "src/../credentials.json",
            str(base / "credentials.json"),
        ):
            out = ws.read_file(spelling)
            assert out == f"Error: path is excluded from this workspace: {spelling}"
            assert "ZQMARKER-SECRET" not in out
        assert ws.write_file("credentials.json", "X").startswith("Error: path is excluded")
        assert ws.delete_file("credentials.json").startswith("Error: path is excluded")


def test_credential_directories_are_refused_as_directories():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, ".ssh/id_ed25519", "ZQMARKER-SECRET\n")
        ws = Workspace(tmp_dir)
        assert ws.list_files(".ssh") == "Error: directory is excluded from this workspace: .ssh"
        assert ws.search_content("ZQMARKER", directory=".ssh") == (
            "Error: directory is excluded from this workspace: .ssh"
        )


def test_allow_paths_still_re_admits_an_excluded_credential_file():
    """The escape hatch for anyone whose agent legitimately reads one of these."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, "credentials.json", "ZQMARKER-ALLOWED\n")
        _write(base, "secrets.yaml", "ZQMARKER-STILL-BLOCKED\n")
        ws = Workspace(tmp_dir, allow_paths=["credentials.json"])
        assert "ZQMARKER-ALLOWED" in ws.read_file("credentials.json")
        assert ws.read_file("secrets.yaml") == "Error: path is excluded from this workspace: secrets.yaml"


# ------------------------------------------------------------------
# Exemptions: "!" entries keep committed env templates readable
# ------------------------------------------------------------------


@pytest.mark.parametrize("rel", ENV_TEMPLATES)
def test_committed_env_templates_are_readable(rel):
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, rel, "OPENAI_API_KEY=\n")
        ws = Workspace(tmp_dir)

        assert "OPENAI_API_KEY" in ws.read_file(rel)
        listed = [e["path"] for e in json.loads(ws.list_files(recursive=True))["files"]]
        assert rel in listed
        assert json.loads(ws.search_content("OPENAI_API_KEY"))["matches_found"] == 1


@pytest.mark.parametrize("rel", ENV_SECRETS)
def test_real_env_files_stay_blocked(rel):
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, rel, "OPENAI_API_KEY=sk-live-secret\n")
        ws = Workspace(tmp_dir)
        assert ws.read_file(rel) == f"Error: path is excluded from this workspace: {rel}"
        assert json.loads(ws.search_content("sk-live-secret"))["matches_found"] == 0


def test_exemption_does_not_reach_inside_an_excluded_directory():
    """An exemption clears the component it names, not the directory above it."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, ".venv/cfg/.env.example", "OPENAI_API_KEY=\n")
        ws = Workspace(tmp_dir)
        assert ws.read_file(".venv/cfg/.env.example") == (
            "Error: path is excluded from this workspace: .venv/cfg/.env.example"
        )


def test_exemptions_can_be_dropped_by_filtering_the_defaults():
    from agno.tools._local_file_utils import DEFAULT_EXCLUDE_PATTERNS

    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, ".env.example", "OPENAI_API_KEY=\n")
        strict = [p for p in DEFAULT_EXCLUDE_PATTERNS if not p.startswith("!")]
        ws = Workspace(tmp_dir, exclude_patterns=strict)
        assert ws.read_file(".env.example") == "Error: path is excluded from this workspace: .env.example"


def test_custom_exclude_patterns_get_no_exemptions_they_did_not_ask_for():
    """You took control: the surface is exactly what you specified."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, ".env.example", "OPENAI_API_KEY=\n")
        ws = Workspace(tmp_dir, exclude_patterns=[".env*"])
        assert ws.read_file(".env.example") == "Error: path is excluded from this workspace: .env.example"


def test_bare_exemption_prefix_is_rejected():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(ValueError, match="names no pattern"):
            Workspace(tmp_dir, exclude_patterns=["!"])


def test_exemption_wins_regardless_of_order():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, "keep.json", "ZQMARKER\n")
        after = Workspace(tmp_dir, exclude_patterns=["*.json", "!keep.json"])
        before = Workspace(tmp_dir, exclude_patterns=["!keep.json", "*.json"])
        assert "ZQMARKER" in after.read_file("keep.json")
        assert "ZQMARKER" in before.read_file("keep.json")


def test_mutating_exclude_patterns_after_construction_takes_effect():
    """exclude_patterns is public and mutable, so the deny/exempt split cannot be a
    one-shot snapshot taken in __init__."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, ".env.example", "OPENAI_API_KEY=\n")
        ws = Workspace(tmp_dir)
        assert "OPENAI_API_KEY" in ws.read_file(".env.example")
        ws.exclude_patterns = [".env*"]
        assert ws.read_file(".env.example") == "Error: path is excluded from this workspace: .env.example"


def test_compiled_matcher_agrees_with_a_pattern_by_pattern_fnmatch():
    """The deny/exempt halves are compiled into one alternation each for speed. Pin the
    equivalence to the loop it replaces, on both case branches, so a translate-level
    difference cannot slip in unseen."""
    from fnmatch import fnmatch, fnmatchcase

    from agno.tools._local_file_utils import DEFAULT_EXCLUDE_PATTERNS, split_exclude_patterns

    names = [
        ".env",
        ".env.example",
        ".env.production",
        "example.env",
        "dist.env",
        "env.example",
        "id_rsa",
        "id_rsa.pub",
        "id_rsa_helper.go",
        "credentials.json",
        "credentials.py",
        "credentials",
        "secrets.py",
        "secrets.yaml",
        "server.pem",
        "key.py",
        "app.py",
        ".ssh",
        ".aws",
        ".venv",
        "build",
        "BUILD",
        ".ENV",
        "Credentials.json",
        "x.TFVARS",
        "service-account.json",
        "serviceAccount.json",
        "known_hosts",
        "!secret.txt",
        "README.md",
        ".DS_Store",
        "x.egg-info",
        "[weird]",
        "a b",
        "*.py",
    ]
    deny, exempt = split_exclude_patterns(DEFAULT_EXCLUDE_PATTERNS)

    with tempfile.TemporaryDirectory() as tmp_dir:
        for fold in (True, False):
            ws = Workspace(tmp_dir)
            ws._fold_case = fold
            match = (lambda a, b: fnmatchcase(a.casefold(), b.casefold())) if fold else fnmatch
            for name in names:
                expected = any(match(name, d) for d in deny) and not any(match(name, e) for e in exempt)
                assert ws._component_excluded(name) is expected, (name, fold)


def test_path_matches_exclude_agrees_with_a_pattern_by_pattern_fnmatch():
    """The FileTools half of the same matcher."""
    from fnmatch import fnmatch

    from agno.tools._local_file_utils import (
        DEFAULT_EXCLUDE_PATTERNS,
        path_matches_exclude,
        split_exclude_patterns,
    )

    deny, exempt = split_exclude_patterns(DEFAULT_EXCLUDE_PATTERNS)
    root = Path("/r")
    for parts in (
        ("app.py",),
        (".env",),
        (".env.example",),
        ("pkg", ".env.example"),
        ("credentials", "loader.py"),
        ("id_rsa",),
        ("src", "secrets.py"),
        (".venv", "cfg", ".env.example"),
        ("!secret.txt",),
    ):
        expected = any(
            any(fnmatch(part, d) for d in deny) and not any(fnmatch(part, e) for e in exempt) for part in parts
        )
        assert path_matches_exclude(root.joinpath(*parts), root, DEFAULT_EXCLUDE_PATTERNS) is expected, parts


def test_empty_deny_list_with_only_exemptions_excludes_nothing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir).resolve()
        _write(base, ".env", "SECRET=1\n")
        ws = Workspace(tmp_dir, exclude_patterns=["!.env.example"])
        assert "SECRET=1" in ws.read_file(".env")
