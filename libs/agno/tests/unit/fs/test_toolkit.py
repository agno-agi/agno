"""Unit tests for FileSystemTools (spec D7/D8): schemas, parity, error strings, injection."""

import inspect
import json

import pytest

from agno.agent import Agent
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.fs.toolkit import FileSystemTools
from agno.team import Team
from agno.tools.function import FunctionCall
from agno.tools.workspace import Workspace

EXPECTED_TOOL_PARAMS = {
    "read_file": ["path", "start_line", "end_line"],
    "write_file": ["path", "content", "overwrite"],
    "append_file": ["path", "content", "unique"],
    "replace_lines": ["path", "start_line", "end_line", "content"],
    "list_files": ["directory", "pattern", "recursive", "max_depth"],
    "search_content": ["query", "directory", "limit"],
    "check_lines": ["lines", "directory"],
    "move_file": ["src", "dst", "overwrite"],
    "delete_file": ["path"],
}

INJECTED_PARAMS = ("run_context", "agent", "team")


@pytest.fixture
def fs(tmp_path) -> FileSystem:
    return FileSystem(backend=LocalFileSystem(root=tmp_path), namespace="radar")


@pytest.fixture
def toolkit(fs) -> FileSystemTools:
    return fs.tools()


class TestSchemas:
    """The empty-schema regression (spec D1): every schema must be non-empty AND
    name every documented parameter AND lack the framework-injected ones."""

    @pytest.mark.parametrize("tool_name", list(EXPECTED_TOOL_PARAMS.keys()))
    def test_schema_names_documented_params_and_lacks_injected(self, toolkit, tool_name):
        function = toolkit.functions[tool_name]
        function.process_entrypoint()
        properties = function.parameters.get("properties", {})
        assert list(properties.keys()) == EXPECTED_TOOL_PARAMS[tool_name]
        for injected in INJECTED_PARAMS:
            assert injected not in properties
        for prop in properties.values():
            assert prop.get("description"), "every model-facing parameter carries its docstring description"

    @pytest.mark.parametrize("tool_name", list(EXPECTED_TOOL_PARAMS.keys()))
    def test_async_schema_names_documented_params(self, toolkit, tool_name):
        function = toolkit.async_functions[tool_name]
        function.process_entrypoint()
        properties = function.parameters.get("properties", {})
        assert list(properties.keys()) == EXPECTED_TOOL_PARAMS[tool_name]
        for injected in INJECTED_PARAMS:
            assert injected not in properties
        # The async agent's prompt surface must be the D7 text, not "Async variant of".
        for prop in properties.values():
            assert prop.get("description"), "every async parameter carries its docstring description"

    @pytest.mark.parametrize("tool_name", list(EXPECTED_TOOL_PARAMS.keys()))
    def test_async_description_matches_sync(self, toolkit, tool_name):
        sync_fn = toolkit.functions[tool_name]
        async_fn = toolkit.async_functions[tool_name]
        sync_fn.process_entrypoint()
        async_fn.process_entrypoint()
        assert async_fn.description == sync_fn.description
        assert "Async variant" not in (async_fn.description or "")


class TestWorkspaceParity:
    """Signatures and defaults match Workspace for every shared parameter of the
    six shared tools; the D7 deviations (no encoding params) are the whole diff."""

    SHARED_TOOLS = ["read_file", "write_file", "list_files", "search_content", "move_file", "delete_file"]
    ALLOWED_MISSING = {"encoding"}  # D7 deviation 1

    @pytest.mark.parametrize("tool_name", SHARED_TOOLS)
    def test_shared_signature_parity(self, tool_name):
        # Per parameter (name -> default), never by index: the trailing
        # keyword-only injected params have no Workspace counterpart (spec D13).
        ws_sig = inspect.signature(getattr(Workspace, tool_name))
        fs_sig = inspect.signature(getattr(FileSystemTools, tool_name))
        ws_defaults = {
            name: p.default
            for name, p in ws_sig.parameters.items()
            if name != "self" and name not in self.ALLOWED_MISSING
        }
        fs_defaults = {
            name: p.default for name, p in fs_sig.parameters.items() if name != "self" and name not in INJECTED_PARAMS
        }
        assert fs_defaults == ws_defaults

    @pytest.mark.parametrize("tool_name", FileSystemTools.FULL_TOOLS)
    def test_injected_params_keyword_only_on_sync_and_async(self, tool_name):
        for method in (getattr(FileSystemTools, tool_name), getattr(FileSystemTools, "a" + tool_name)):
            signature = inspect.signature(method)
            for injected in INJECTED_PARAMS:
                param = signature.parameters[injected]
                assert param.kind == inspect.Parameter.KEYWORD_ONLY
                assert param.default is None

    def test_no_encoding_params_anywhere(self):
        for tool_name in FileSystemTools.FULL_TOOLS:
            signature = inspect.signature(getattr(FileSystemTools, tool_name))
            assert "encoding" not in signature.parameters

    def test_no_run_command_or_edit_file(self, toolkit):
        assert "run_command" not in toolkit.functions
        assert "edit_file" not in toolkit.functions
        assert not hasattr(toolkit, "run_command")
        assert not hasattr(toolkit, "edit_file")

    def test_no_confirmation_by_default(self, toolkit):
        assert toolkit.requires_confirmation_tools == []

    def test_confirmation_opt_in_via_kwargs(self, fs):
        tk = fs.tools(requires_confirmation_tools=["delete_file"])
        assert tk.functions["delete_file"].requires_confirmation is True


class TestSurface:
    def test_full_surface_registers_nine_sync_and_async(self, toolkit):
        assert list(toolkit.functions.keys()) == FileSystemTools.FULL_TOOLS
        assert list(toolkit.async_functions.keys()) == FileSystemTools.FULL_TOOLS

    def test_read_only_registers_exactly_four(self, fs):
        tk = fs.tools(read_only=True)
        assert list(tk.functions.keys()) == FileSystemTools.READ_ONLY_TOOLS
        assert list(tk.async_functions.keys()) == FileSystemTools.READ_ONLY_TOOLS

    def test_toolkit_name(self, toolkit):
        assert toolkit.name == "filesystem"

    def test_surface_drift_guard_sync_and_async_methods_exist(self):
        for tool_name in FileSystemTools.FULL_TOOLS:
            assert callable(getattr(FileSystemTools, tool_name))
            assert callable(getattr(FileSystemTools, "a" + tool_name))


class TestInstructions:
    def test_toolkit_carries_instructions(self, toolkit):
        assert toolkit.add_instructions is True
        assert toolkit.instructions == FileSystem.instructions()
        assert 'check_lines(lines, directory="seen")' in toolkit.instructions

    def test_static_call_without_instance(self):
        text = FileSystem.instructions()
        assert text.startswith("You have your own private, durable filesystem")
        assert "Never store secrets, passwords, or API keys." in text

    def test_read_only_variant_names_no_write_tool(self, fs):
        text = FileSystem.instructions(read_only=True)
        for write_tool in ("append_file", "write_file", "delete_file", "move_file"):
            assert write_tool not in text
        # Assert the contract, not the phrasing: read-only must describe read access
        # and say the files cannot be changed.
        assert "read access" in text
        assert "cannot change these files" in text
        tk = fs.tools(read_only=True)
        assert tk.instructions == text

    def test_namespace_never_in_instructions(self, fs):
        assert "radar" not in FileSystem.instructions()
        assert "namespace" not in FileSystem.instructions().lower()
        assert "namespace" not in FileSystem.instructions(read_only=True).lower()


class TestReadFileTool:
    def test_cat_n_line_numbering(self, fs, toolkit):
        fs.write("a.md", "alpha\nbeta\n")
        assert toolkit.read_file("a.md") == "     1\talpha\n     2\tbeta"

    def test_chunk_numbering_reflects_actual_lines(self, fs, toolkit):
        fs.write("a.md", "l1\nl2\nl3\nl4\n")
        assert toolkit.read_file("a.md", start_line=3, end_line=4) == "     3\tl3\n     4\tl4"

    def test_missing_file(self, toolkit):
        assert toolkit.read_file("nope.md") == "Error: file not found: nope.md"

    def test_too_long_guard_at_max_read_chars(self, tmp_path):
        # A context budget in chars, deliberately not max_file_bytes: comparing a
        # char count against a byte cap made this guard unreachable.
        from agno.fs.toolkit import _MAX_READ_CHARS

        backend = LocalFileSystem(root=tmp_path)
        fs = FileSystem(backend=backend, namespace="radar")
        toolkit = fs.tools()
        oversized = _MAX_READ_CHARS + 1
        backend.write("radar", "big.md", "x" * oversized)
        result = toolkit.read_file("big.md")
        assert result.startswith(f"Error: file too long to read whole ({oversized} chars")
        assert f"limit {_MAX_READ_CHARS} chars" in result
        assert "start_line/end_line" in result
        # A file the agent is allowed to write is a file it can read back whole.
        backend.write("radar", "at-cap.md", "y" * 50)
        assert toolkit.read_file("at-cap.md").startswith("     1\t")

    def test_too_long_guard_bypassed_for_chunked_read(self, tmp_path):
        backend = LocalFileSystem(root=tmp_path)
        fs = FileSystem(backend=backend, namespace="radar", max_file_bytes=10)
        toolkit = fs.tools()
        backend.write("radar", "big.md", "line1\nline2\nline3\n")
        assert toolkit.read_file("big.md", start_line=2, end_line=2) == "     2\tline2"


class TestErrorStringsVerbatim:
    def test_write_exists(self, fs, toolkit):
        fs.write("a.md", "x")
        assert toolkit.write_file("a.md", "y", overwrite=False) == "Error: file exists and overwrite=False: a.md"

    def test_move_dst_exists(self, fs, toolkit):
        fs.write("a.md", "x")
        fs.write("b.md", "y")
        assert toolkit.move_file("a.md", "b.md") == "Error: dst exists and overwrite=False: b.md"

    def test_move_missing_src(self, toolkit):
        assert toolkit.move_file("missing.md", "b.md") == "Error: file not found: missing.md"

    def test_delete_missing(self, toolkit):
        assert toolkit.delete_file("a.md") == "Error: file not found: a.md"

    def test_quota_file_string(self, tmp_path):
        fs = FileSystem(backend=LocalFileSystem(root=tmp_path), namespace="radar", max_file_bytes=10)
        toolkit = fs.tools()
        result = toolkit.write_file("a.md", "0123456789x")
        assert result == (
            "Error: a.md would be 11 bytes (limit 10 per file). "
            "Start a new file (for record logs, partition by date, e.g. seen/2026-07-24.md) "
            "or delete files you no longer need."
        )

    def test_quota_namespace_string(self, tmp_path):
        fs = FileSystem(backend=LocalFileSystem(root=tmp_path), namespace="radar", max_namespace_bytes=10)
        toolkit = fs.tools()
        toolkit.write_file("a.md", "123456")
        result = toolkit.write_file("b.md", "78901")
        assert result == (
            "Error: storage is full (6 of 10 bytes). Delete only files you are certain are obsolete "
            "(see list_files), such as an old date partition, then retry. Do not overwrite or delete "
            "records you might still need to make room; if nothing is safely disposable, stop and "
            "report that storage is full."
        )

    def test_check_lines_count_string(self, toolkit):
        result = toolkit.check_lines(["x"] * 201)
        assert result == "Error: too many records (201 > 200). Check them in batches of 200 or fewer."

    def test_check_lines_record_string(self, toolkit):
        result = toolkit.check_lines(["ok", "bad\nrecord"])
        assert result == "Error: invalid record 'bad\\nrecord': records must be single lines with no newlines."

    def test_append_file_interior_cr_record_string(self, toolkit):
        result = toolkit.append_file("log.md", "a\rb")
        assert result == "Error: invalid record 'a\\rb': records must be single lines with no newlines."

    def test_invalid_path_string(self, toolkit):
        result = toolkit.read_file("../escape.md")
        assert result.startswith("Error: invalid path '../escape.md': ")
        assert result.endswith("Use relative paths like notes/topic.md.")

    def test_empty_query_string(self, toolkit):
        assert toolkit.search_content("") == "Error: query cannot be empty"
        assert toolkit.search_content("   ") == "Error: query cannot be empty"


class TestSuccessStrings:
    def test_write_reports_bytes_not_chars(self, toolkit):
        # 1 char, 4 bytes: the quota unit and the reported unit must agree.
        assert toolkit.write_file("a.md", "\U0001f600") == "Wrote 4 bytes to a.md"

    def test_append_reports_bytes_and_new_size(self, toolkit):
        assert toolkit.append_file("log.md", "one\n") == "Appended 4 bytes to log.md (now 4 bytes)"
        assert toolkit.append_file("log.md", "two") == "Appended 4 bytes to log.md (now 8 bytes)"

    def test_append_empty_reports_zero(self, toolkit):
        toolkit.append_file("log.md", "one\n")
        assert toolkit.append_file("log.md", "") == "Appended 0 bytes to log.md (now 4 bytes)"
        assert toolkit.append_file("other.md", "\n") == "Appended 0 bytes to other.md (now 0 bytes)"

    def test_move_and_delete_strings(self, fs, toolkit):
        fs.write("a.md", "x")
        assert toolkit.move_file("a.md", "b.md") == "Moved a.md -> b.md"
        assert toolkit.delete_file("b.md") == "Deleted b.md"


class TestListFilesTool:
    def test_json_shape_and_usage_key(self, fs, toolkit):
        fs.write("seen/a.md", "12345")
        payload = json.loads(toolkit.list_files())
        assert set(payload.keys()) == {"directory", "pattern", "recursive", "files", "usage"}
        assert payload["directory"] == "."
        assert payload["usage"] == {"files": 1, "bytes_used": 5, "bytes_limit": fs.max_namespace_bytes}
        assert {"path": "seen", "type": "dir", "size": None, "updated": None} in payload["files"]

    def test_entry_shape_matches_workspace(self, fs, toolkit):
        fs.write("a.md", "12345")
        payload = json.loads(toolkit.list_files())
        entry = payload["files"][0]
        assert entry["path"] == "a.md" and entry["type"] == "file" and entry["size"] == "5B"
        # `updated` is what makes the quota guidance actionable: the model can see age.
        assert entry["updated"].endswith("Z")

    def test_non_recursive_lists_only_top_level(self, fs, toolkit):
        fs.write("x.md", "1")
        fs.write("a/y.md", "2")
        fs.write("a/b/z.md", "3")
        payload = json.loads(toolkit.list_files())
        assert [(e["path"], e["type"]) for e in payload["files"]] == [("a", "dir"), ("x.md", "file")]

    def test_recursive_max_depth_boundary_enumerated(self, fs, toolkit):
        # With max_depth=1, returned paths carry up to TWO segments below the
        # directory: the boundary directory is itself enumerated (spec D7/D13).
        fs.write("x.md", "1")
        fs.write("a/y.md", "2")
        fs.write("a/b/z.md", "3")
        fs.write("a/b/c/deep.md", "4")
        payload = json.loads(toolkit.list_files(recursive=True, max_depth=1))
        listed = {e["path"] for e in payload["files"]}
        assert listed == {"x.md", "a", "a/y.md", "a/b"}

    def test_recursive_default_depth(self, fs, toolkit):
        fs.write("a/b/c/deep.md", "4")
        payload = json.loads(toolkit.list_files(recursive=True))
        listed = {e["path"] for e in payload["files"]}
        assert "a/b/c/deep.md" in listed

    def test_empty_pattern_means_no_filter(self, fs, toolkit):
        # Models pass pattern="" — Workspace treats it as falsy, so must we.
        fs.write("notes/a.md", "1")
        payload = json.loads(toolkit.list_files(pattern="", recursive=True))
        assert {e["path"] for e in payload["files"]} == {"notes", "notes/a.md"}

    def test_pattern_fnmatch_on_basename_both_modes(self, fs, toolkit):
        fs.write("a.md", "1")
        fs.write("b.txt", "2")
        fs.write("sub/c.md", "3")
        flat = json.loads(toolkit.list_files(pattern="*.md"))
        assert {e["path"] for e in flat["files"]} == {"a.md"}
        deep = json.loads(toolkit.list_files(pattern="*.md", recursive=True))
        assert {e["path"] for e in deep["files"]} == {"a.md", "sub/c.md"}

    def test_directory_scoped_listing(self, fs, toolkit):
        fs.write("seen/a.md", "1")
        fs.write("seen-old/b.md", "2")
        payload = json.loads(toolkit.list_files("seen"))
        assert [e["path"] for e in payload["files"]] == ["seen/a.md"]

    def test_dir_entries_capped(self, tmp_path):
        from agno.fs.toolkit import _MAX_DIR_ENTRIES

        backend = LocalFileSystem(root=tmp_path)
        for i in range(_MAX_DIR_ENTRIES + 1):
            backend.write("radar", f"d{i:04d}/f.md", "x")
        fs = FileSystem(backend=backend, namespace="radar")
        payload = json.loads(fs.tools().list_files())
        dir_entries = [e for e in payload["files"] if e["type"] == "dir"]
        assert len(dir_entries) == _MAX_DIR_ENTRIES + 1  # capped + the truncation marker
        assert dir_entries[-1]["path"] == "...and 1 more"
        assert payload["files"][-1]["path"] == "...and 1 more"


class TestContentExposure:
    """Only read_file and search_content return content (spec D7)."""

    def test_metadata_tools_never_leak_content(self, fs, toolkit):
        sentinel = "SENTINEL-CONTENT-XYZZY"
        outputs = [
            toolkit.write_file("a.md", sentinel),
            toolkit.append_file("log.md", sentinel),
            toolkit.check_lines([sentinel]),
            toolkit.list_files(),
            toolkit.move_file("a.md", "b.md"),
            toolkit.delete_file("b.md"),
        ]
        # check_lines echoes the queried lines (model-supplied), never file content;
        # everything else is pure metadata.
        for output in (outputs[0], outputs[1], outputs[3], outputs[4], outputs[5]):
            assert sentinel not in output

    def test_read_and_search_do_return_content(self, fs, toolkit):
        fs.write("a.md", "the content body")
        assert "the content body" in toolkit.read_file("a.md")
        assert "the content body" in toolkit.search_content("content body")


class TestTemplatedResolution:
    """Placeholder resolution from injected context only, fail closed (spec D2)."""

    @pytest.fixture
    def user_toolkit(self, tmp_path):
        backend = LocalFileSystem(root=tmp_path)
        fs = FileSystem(backend=backend, namespace="radar/{user_id}")
        return backend, fs.tools()

    def test_missing_user_id_fails_closed(self, user_toolkit):
        _backend, toolkit = user_toolkit
        expected = "Error: this agent's files require user_id for this run and none was provided."
        assert toolkit.append_file("seen/a.md", "x") == expected
        assert toolkit.read_file("seen/a.md") == expected
        assert toolkit.list_files() == expected
        assert toolkit.check_lines(["x"]) == expected

    def test_user_id_resolves_from_run_context(self, user_toolkit):
        from agno.run import RunContext

        backend, toolkit = user_toolkit
        run_context = RunContext(run_id="r1", session_id="s1", user_id="u42")
        result = toolkit.append_file("seen/a.md", "hello", run_context=run_context)
        assert result.startswith("Appended 6 bytes")
        assert backend.read("radar/u42", "seen/a.md") == "hello\n"
        other = RunContext(run_id="r2", session_id="s2", user_id="u43")
        assert toolkit.read_file("seen/a.md", run_context=other) == "Error: file not found: seen/a.md"

    def test_agent_id_resolves_on_plain_agent(self, tmp_path):
        backend = LocalFileSystem(root=tmp_path)
        fs = FileSystem(backend=backend, namespace="ws/{agent_id}")
        toolkit = fs.tools()
        agent = Agent(id="agent-1", name="Radar")
        result = toolkit.append_file("notes/a.md", "x", agent=agent)
        assert result.startswith("Appended")
        assert backend.read("ws/agent-1", "notes/a.md") == "x\n"

    def test_agent_id_fails_closed_on_team_leader(self, tmp_path):
        # A Team leader's own tools get `team` injected but never `agent`
        # (team/_tools.py), so a leader-attached {agent_id} fails closed.
        fs = FileSystem(backend=LocalFileSystem(root=tmp_path), namespace="ws/{agent_id}")
        toolkit = fs.tools()
        member = Agent(id="member-1", name="Member")
        team = Team(id="team-1", name="T", members=[member])
        result = toolkit.append_file("notes/a.md", "x", team=team)
        assert result == "Error: this agent's files require agent_id for this run and none was provided."

    def test_team_id_resolves_on_leader_and_member(self, tmp_path):
        backend = LocalFileSystem(root=tmp_path)
        fs = FileSystem(backend=backend, namespace="shared/{team_id}")
        toolkit = fs.tools()
        member = Agent(id="member-1", name="Member")
        team = Team(id="team-1", name="T", members=[member])
        # Leader surface: team injected, no agent.
        assert toolkit.append_file("a.md", "from-leader", team=team).startswith("Appended")
        # Member surface: the member's own agent plus the propagated team.
        assert toolkit.append_file("a.md", "from-member", agent=member, team=team).startswith("Appended")
        content = backend.read("shared/team-1", "a.md")
        assert content == "from-leader\nfrom-member\n"

    def test_team_id_fails_closed_on_plain_agent(self, tmp_path):
        fs = FileSystem(backend=LocalFileSystem(root=tmp_path), namespace="shared/{team_id}")
        toolkit = fs.tools()
        agent = Agent(id="agent-1", name="Solo")
        result = toolkit.append_file("a.md", "x", agent=agent)
        assert result == "Error: this agent's files require team_id for this run and none was provided."

    def test_model_supplied_argument_cannot_redirect(self, user_toolkit):
        # A model smuggling strings into the injected parameter names must not
        # be able to pick a namespace: strings carry no identity attributes.
        _backend, toolkit = user_toolkit
        result = toolkit.append_file("a.md", "x", run_context="hostile", team="hostile")
        assert result == "Error: this agent's files require user_id for this run and none was provided."

    def test_resolution_through_real_function_call_machinery(self, tmp_path):
        backend = LocalFileSystem(root=tmp_path)
        fs = FileSystem(backend=backend, namespace="shared/{team_id}")
        toolkit = fs.tools()
        member = Agent(id="member-1", name="Member")
        team = Team(id="team-1", name="T", members=[member])
        function = toolkit.functions["append_file"]
        function.process_entrypoint()
        function._team = team
        fc = FunctionCall(function=function, arguments={"path": "a.md", "content": "via-fc"})
        fc.execute()
        assert backend.read("shared/team-1", "a.md") == "via-fc\n"
        assert isinstance(fc.result, str) and fc.result.startswith("Appended")


class TestListFilesBounded:
    def test_file_entries_capped_like_dir_entries(self, tmp_path):
        # The namespace quota bounds BYTES, not entry count: many tiny files must
        # not dump an unbounded listing into the model's context (PR review).
        import json

        from agno.fs.toolkit import _MAX_DIR_ENTRIES

        fs = FileSystem(backend=LocalFileSystem(root=tmp_path), namespace="many")
        extra = 20
        for i in range(_MAX_DIR_ENTRIES + extra):
            fs.write(f"f{i:04d}.md", "x")
        payload = json.loads(fs.tools().list_files())
        files = [e for e in payload["files"] if e["type"] == "file"]
        assert len(files) == _MAX_DIR_ENTRIES + 1  # capped + the "...and N more" marker
        assert files[-1]["path"] == f"...and {extra} more"


class TestReadFileRanges:
    """Every out-of-range read must name the problem. An empty string is
    indistinguishable from an empty file and leaves the model nothing to act on."""

    @pytest.fixture
    def three_lines(self, fs, toolkit):
        fs.write("a.md", "l1\nl2\nl3\n")
        return toolkit

    def test_inverted_range_is_an_error(self, three_lines):
        assert three_lines.read_file("a.md", start_line=3, end_line=2).startswith("Error: end_line 2 is before")

    def test_start_past_eof_names_the_line_count(self, three_lines):
        result = three_lines.read_file("a.md", start_line=999)
        assert result.startswith("Error: start_line 999 is past the end")
        assert "3 lines" in result

    def test_zero_and_negative_starts_are_errors(self, three_lines):
        assert three_lines.read_file("a.md", start_line=0).startswith("Error: start_line must be 1 or greater")
        assert three_lines.read_file("a.md", start_line=-5).startswith("Error: start_line must be 1 or greater")

    def test_empty_file_says_so_rather_than_returning_nothing(self, fs, toolkit):
        fs.write("empty.md", "")
        assert toolkit.read_file("empty.md") == "(empty.md is empty)"

    def test_valid_range_still_reads(self, three_lines):
        assert three_lines.read_file("a.md", start_line=2, end_line=3) == "     2\tl2\n     3\tl3"

    def test_end_past_eof_clamps_instead_of_erroring(self, three_lines):
        assert three_lines.read_file("a.md", start_line=3, end_line=99) == "     3\tl3"


class TestReadFileSizeGuard:
    def test_guard_fires_below_the_storage_cap(self, fs, toolkit):
        # The old guard compared chars against max_file_bytes. UTF-8 gives
        # chars <= bytes, so any file the store accepted always passed and a
        # whole 1MB file could land in context.
        from agno.fs.toolkit import _MAX_READ_CHARS

        fs.write("big.md", "x" * (_MAX_READ_CHARS + 1))
        result = toolkit.read_file("big.md")
        assert result.startswith("Error: file too long to read whole")
        assert str(_MAX_READ_CHARS) in result
        assert _MAX_READ_CHARS < fs.max_file_bytes, "a context budget, not the storage cap"

    def test_ranged_read_still_works_on_an_oversized_file(self, fs, toolkit):
        from agno.fs.toolkit import _MAX_READ_CHARS

        fs.write("big.md", "\n".join("line" for _ in range(_MAX_READ_CHARS)))
        assert toolkit.read_file("big.md", start_line=1, end_line=2) == "     1\tline\n     2\tline"


class TestSearchLocatesMatches:
    def test_match_carries_line_number_and_count(self, fs, toolkit):
        fs.write("notes/big.md", "\n".join("hit" if i in (3, 7) else "filler" for i in range(10)))
        payload = json.loads(toolkit.search_content("hit"))
        match = payload["files"][0]
        assert match["line"] == 4  # 1-indexed
        assert match["matches"] == 2

    def test_line_number_feeds_read_file(self, fs, toolkit):
        fs.write("a.md", "\n".join(f"line{i}" for i in range(50)) + "\nNEEDLE\n")
        line = json.loads(toolkit.search_content("NEEDLE"))["files"][0]["line"]
        assert toolkit.read_file("a.md", start_line=line, end_line=line) == f"{line:6d}\tNEEDLE"


class TestAppendUnique:
    def test_unique_skips_lines_already_present(self, fs, toolkit):
        toolkit.append_file("seen/a.md", "rec-1\nrec-2")
        result = toolkit.append_file("seen/a.md", "rec-2\nrec-3", unique=True)
        assert fs.read("seen/a.md") == "rec-1\nrec-2\nrec-3\n"
        assert result.startswith("Appended 6 bytes")

    def test_unique_dedupes_within_the_chunk(self, fs, toolkit):
        toolkit.append_file("seen/a.md", "rec-1\nrec-1\nrec-2", unique=True)
        assert fs.read("seen/a.md") == "rec-1\nrec-2\n"

    def test_unique_all_present_is_a_no_op(self, fs, toolkit):
        toolkit.append_file("seen/a.md", "rec-1")
        result = toolkit.append_file("seen/a.md", "rec-1", unique=True)
        assert "every line was already present" in result
        assert fs.read("seen/a.md") == "rec-1\n"

    def test_default_still_appends_duplicates(self, fs, toolkit):
        toolkit.append_file("seen/a.md", "rec-1")
        toolkit.append_file("seen/a.md", "rec-1")
        assert fs.read("seen/a.md") == "rec-1\nrec-1\n"

    def test_unique_on_a_missing_file_creates_it(self, fs, toolkit):
        toolkit.append_file("seen/new.md", "rec-1", unique=True)
        assert fs.read("seen/new.md") == "rec-1\n"


class TestReplaceLines:
    @pytest.fixture
    def four_lines(self, fs, toolkit):
        fs.write("a.md", "one\ntwo\nthree\nfour\n")
        return toolkit

    def test_replace_a_middle_range(self, fs, four_lines):
        assert four_lines.replace_lines("a.md", 2, 3, "TWO\nTHREE").startswith("Replaced lines 2-3")
        assert fs.read("a.md") == "one\nTWO\nTHREE\nfour\n"

    def test_replace_with_fewer_lines(self, fs, four_lines):
        four_lines.replace_lines("a.md", 2, 3, "MERGED")
        assert fs.read("a.md") == "one\nMERGED\nfour\n"

    def test_empty_content_deletes_the_range(self, fs, four_lines):
        assert four_lines.replace_lines("a.md", 2, 3).startswith("Deleted lines 2-3")
        assert fs.read("a.md") == "one\nfour\n"

    def test_delete_a_single_record_line(self, fs, toolkit):
        # The correction path a record log otherwise lacks.
        toolkit.append_file("seen/a.md", "rec-1\nBAD\nrec-3")
        toolkit.replace_lines("seen/a.md", 2, 2)
        assert fs.read("seen/a.md") == "rec-1\nrec-3\n"

    def test_trailing_newline_is_preserved_either_way(self, fs, toolkit):
        fs.write("no-nl.md", "one\ntwo")
        toolkit.replace_lines("no-nl.md", 1, 1, "ONE")
        assert fs.read("no-nl.md") == "ONE\ntwo"

    def test_missing_file_errors(self, toolkit):
        assert toolkit.replace_lines("nope.md", 1, 1, "x") == "Error: file not found: nope.md"

    def test_range_past_eof_errors(self, four_lines):
        result = four_lines.replace_lines("a.md", 99, 100, "x")
        assert result.startswith("Error: start_line 99 is past the end")
        assert "4 lines" in result

    def test_inverted_range_errors(self, four_lines):
        assert four_lines.replace_lines("a.md", 3, 2, "x").startswith("Error: end_line must be greater")

    def test_end_past_eof_clamps(self, fs, four_lines):
        four_lines.replace_lines("a.md", 3, 99, "THREE")
        assert fs.read("a.md") == "one\ntwo\nTHREE\n"

    def test_not_in_the_read_only_surface(self, fs):
        assert "replace_lines" not in fs.tools(read_only=True).functions
