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
    "move_file",
    "delete_file",
    "run_command",
]
READ_METHODS = ["read_file", "list_files", "search_content"]
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
