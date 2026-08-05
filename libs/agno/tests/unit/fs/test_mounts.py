"""Unit tests for FileSystem mounts: one agent, several namespaces, one tool surface.

Mounts are developer-declared top-level directory names routing to another
FileSystem (read-only by default). The contract under test: routing by first
path segment, ro enforcement as error strings (never exceptions), no
cross-store moves, zero tool-schema surface change, per-store quotas, and
per-call resolution of templated mounted namespaces.
"""

import json

import pytest

from agno.fs import FileSystem, Mount
from agno.fs.errors import InvalidPathError
from agno.fs.local import LocalFileSystem
from agno.fs.toolkit import FileSystemTools

RO_ERROR = "Error: shared/ is read-only: files in this shared mount can be read but not changed."


@pytest.fixture
def backend(tmp_path) -> LocalFileSystem:
    return LocalFileSystem(root=tmp_path)


@pytest.fixture
def primary(backend) -> FileSystem:
    return FileSystem(backend=backend, namespace="brain")


@pytest.fixture
def shared(backend) -> FileSystem:
    return FileSystem(backend=backend, namespace="global")


@pytest.fixture
def ro_tools(primary, shared) -> FileSystemTools:
    # Bare FileSystem value: coerces to a read-only Mount.
    return primary.tools(mounts={"shared": shared})


@pytest.fixture
def rw_tools(primary, shared) -> FileSystemTools:
    return primary.tools(allow_delete=True, mounts={"team": Mount(fs=shared, mode="rw")})


class TestMountDeclaration:
    """Mount names are validated at construction; bad declarations never build."""

    @pytest.mark.parametrize(
        "bad_name",
        [".", "..", "a/b", "/", "", "a b", "{user_id}", "a{b}", "a\\b", "a\nb", "sh:ared", "x" * 129],
    )
    def test_bad_mount_names_rejected(self, primary, shared, bad_name):
        with pytest.raises(InvalidPathError):
            primary.tools(mounts={bad_name: shared})

    def test_non_string_mount_name_rejected(self, primary, shared):
        with pytest.raises(InvalidPathError):
            primary.tools(mounts={7: shared})  # type: ignore[dict-item]

    def test_uppercase_name_normalizes_to_lowercase(self, primary, shared):
        toolkit = primary.tools(mounts={"Shared": shared})
        assert list(toolkit.mounts.keys()) == ["shared"]

    def test_duplicate_after_normalization_rejected(self, primary, shared):
        with pytest.raises(InvalidPathError):
            primary.tools(mounts={"Shared": shared, "shared": shared})

    def test_bare_filesystem_coerces_to_read_only_mount(self, ro_tools):
        mount = ro_tools.mounts["shared"]
        assert isinstance(mount, Mount)
        assert mount.mode == "ro"

    def test_bad_mount_value_type_rejected(self, primary):
        with pytest.raises(TypeError):
            primary.tools(mounts={"shared": "not-a-filesystem"})  # type: ignore[dict-item]

    def test_bad_mode_rejected(self, primary, shared):
        with pytest.raises(ValueError):
            primary.tools(mounts={"shared": Mount(fs=shared, mode="rwx")})  # type: ignore[arg-type]

    def test_mount_fs_must_be_a_filesystem(self, primary):
        with pytest.raises(TypeError):
            primary.tools(mounts={"shared": Mount(fs="nope")})  # type: ignore[arg-type]

    def test_no_mounts_means_empty_dict(self, primary):
        assert primary.tools().mounts == {}


class TestRouting:
    def test_read_via_mount_prefix_hits_the_mounted_store(self, shared, ro_tools):
        shared.write("notes/decisions.md", "we chose postgres\n")
        assert "we chose postgres" in ro_tools.read_file("shared/notes/decisions.md")

    def test_primary_paths_are_unaffected(self, primary, ro_tools):
        primary.write("notes/mine.md", "my own note\n")
        assert "my own note" in ro_tools.read_file("notes/mine.md")
        # And a primary path does not leak into the mount.
        assert ro_tools.read_file("shared/notes/mine.md") == "Error: file not found: shared/notes/mine.md"

    def test_mount_prefix_matches_case_insensitively(self, shared, ro_tools):
        # Mount names are lowercase identifiers, so SHARED/ and shared/ are one mount.
        shared.write("a.md", "x\n")
        assert "1\tx" in ro_tools.read_file("SHARED/a.md")

    def test_mount_name_alone_is_not_a_file(self, ro_tools):
        result = ro_tools.read_file("shared")
        assert result == (
            "Error: shared/ is a shared mount, not a file. Give a path inside it, like "
            'shared/notes/topic.md, or list it with list_files(directory="shared").'
        )

    def test_deleting_the_mount_itself_is_refused(self, primary, shared):
        toolkit = primary.tools(allow_delete=True, mounts={"team": Mount(fs=shared, mode="rw")})
        result = toolkit.delete_file("team")
        assert result.startswith("Error: team/ is a shared mount, not a file.")

    def test_writes_route_to_the_mount_not_a_shadowed_primary_path(self, primary, shared, rw_tools):
        # The loud-write rule: a write whose first segment names a mount goes to
        # the mount; it must never silently land in the primary namespace.
        rw_tools.write_file("team/plan.md", "the plan\n")
        assert shared.read("plan.md") == "the plan\n"
        assert primary.read("team/plan.md") is None


class TestReadOnlyEnforcement:
    """Every write-family tool refuses an ro mount with the standard error string:
    no exception reaches the model, and nothing is written."""

    def test_write_file_refused(self, shared, ro_tools):
        assert ro_tools.write_file("shared/a.md", "x") == RO_ERROR
        assert shared.read("a.md") is None

    def test_append_file_refused(self, shared, ro_tools):
        assert ro_tools.append_file("shared/log.md", "rec-1") == RO_ERROR
        assert shared.read("log.md") is None

    def test_replace_lines_refused(self, shared, ro_tools):
        shared.write("a.md", "one\ntwo\n")
        assert ro_tools.replace_lines("shared/a.md", 1, 1, "ONE") == RO_ERROR
        assert shared.read("a.md") == "one\ntwo\n"

    def test_move_file_refused_as_src(self, shared, ro_tools):
        shared.write("a.md", "x\n")
        assert ro_tools.move_file("shared/a.md", "shared/b.md") == RO_ERROR
        assert shared.read("a.md") == "x\n"

    def test_move_into_an_ro_mount_refused(self, primary, ro_tools):
        primary.write("a.md", "x\n")
        assert ro_tools.move_file("a.md", "shared/a.md") == RO_ERROR
        assert primary.read("a.md") == "x\n"

    def test_delete_file_refused(self, primary, shared):
        toolkit = primary.tools(allow_delete=True, mounts={"shared": shared})
        shared.write("a.md", "x\n")
        assert toolkit.delete_file("shared/a.md") == RO_ERROR
        assert shared.read("a.md") == "x\n"

    def test_reads_still_work_on_an_ro_mount(self, shared, ro_tools):
        shared.write("a.md", "readable\n")
        assert "readable" in ro_tools.read_file("shared/a.md")
        assert "a.md" in ro_tools.list_files(directory="shared")


class TestReadWriteMount:
    def test_write_lands_in_the_mounted_store_only(self, primary, shared, rw_tools):
        assert rw_tools.write_file("team/notes/a.md", "hello") == "Wrote 5 bytes to team/notes/a.md"
        assert shared.read("notes/a.md") == "hello"
        assert primary.read("team/notes/a.md") is None
        assert primary.usage().total_bytes == 0

    def test_append_and_replace_through_the_mount(self, shared, rw_tools):
        rw_tools.append_file("team/log.md", "rec-1\nrec-2")
        assert shared.read("log.md") == "rec-1\nrec-2\n"
        rw_tools.replace_lines("team/log.md", 1, 1, "REC-1")
        assert shared.read("log.md") == "REC-1\nrec-2\n"

    def test_delete_through_the_mount(self, shared, rw_tools):
        shared.write("a.md", "x\n")
        assert rw_tools.delete_file("team/a.md") == "Deleted team/a.md"
        assert shared.read("a.md") is None

    def test_move_within_one_mount_works(self, shared, rw_tools):
        shared.write("a.md", "x\n")
        assert rw_tools.move_file("team/a.md", "team/archive/a.md") == "Moved team/a.md -> team/archive/a.md"
        assert shared.read("archive/a.md") == "x\n"


class TestCrossStoreMove:
    """A move never crosses file stores: refused with a clear error, src intact."""

    def test_primary_to_mount_refused(self, primary, rw_tools):
        primary.write("a.md", "x\n")
        result = rw_tools.move_file("a.md", "team/a.md")
        assert result == (
            "Error: cannot move between file stores: a.md is in your own files and team/a.md is in "
            "team/. Copy it instead with read_file + write_file, then delete the original if you can."
        )
        assert primary.read("a.md") == "x\n"

    def test_mount_to_primary_refused(self, shared, rw_tools):
        shared.write("a.md", "x\n")
        result = rw_tools.move_file("team/a.md", "a.md")
        assert result.startswith("Error: cannot move between file stores:")
        assert shared.read("a.md") == "x\n"

    def test_mount_to_mount_refused(self, primary, backend):
        other = FileSystem(backend=backend, namespace="other")
        toolkit = primary.tools(mounts={"a": Mount(fs=primary, mode="rw"), "b": Mount(fs=other, mode="rw")})
        primary.write("x.md", "x\n")
        result = toolkit.move_file("a/x.md", "b/x.md")
        assert result.startswith("Error: cannot move between file stores:")
        assert primary.read("x.md") == "x\n"
        assert other.read("x.md") is None


class TestListFiles:
    def test_root_listing_surfaces_mounts_as_dir_entries(self, primary, ro_tools):
        primary.write("notes/a.md", "x\n")
        payload = json.loads(ro_tools.list_files())
        assert {"path": "shared", "type": "dir", "size": None, "updated": None, "mount": "ro"} in payload["files"]

    def test_rw_mount_entry_reports_its_mode(self, rw_tools):
        payload = json.loads(rw_tools.list_files())
        assert {"path": "team", "type": "dir", "size": None, "updated": None, "mount": "rw"} in payload["files"]

    def test_root_listing_never_descends_into_a_mount(self, shared, ro_tools):
        shared.write("notes/deep.md", "x\n")
        payload = json.loads(ro_tools.list_files(recursive=True))
        paths = {e["path"] for e in payload["files"]}
        assert "shared" in paths
        assert "shared/notes/deep.md" not in paths

    def test_scoped_listing_returns_paths_the_model_can_read_back(self, shared, ro_tools):
        shared.write("notes/a.md", "round trip\n")
        payload = json.loads(ro_tools.list_files(directory="shared", recursive=True))
        paths = [e["path"] for e in payload["files"] if e["type"] == "file"]
        assert paths == ["shared/notes/a.md"]
        assert "round trip" in ro_tools.read_file(paths[0])

    def test_scoped_listing_reports_the_mounted_stores_usage(self, primary, backend, ro_tools):
        shared_small = FileSystem(backend=backend, namespace="tiny", max_namespace_bytes=100)
        toolkit = primary.tools(mounts={"tiny": shared_small})
        shared_small.write("a.md", "12345")
        payload = json.loads(toolkit.list_files(directory="tiny"))
        assert payload["usage"] == {"files": 1, "bytes_used": 5, "bytes_limit": 100}

    def test_pattern_filters_mount_entries_like_other_dirs(self, ro_tools):
        payload = json.loads(ro_tools.list_files(pattern="*.md"))
        assert "shared" not in {e["path"] for e in payload["files"]}
        kept = json.loads(ro_tools.list_files(pattern="shar*"))
        assert "shared" in {e["path"] for e in kept["files"]}

    def test_shadowed_primary_paths_are_dropped_from_listings(self, primary, ro_tools):
        # A primary file under a mount name is unreachable through the tools
        # (the router sends that prefix to the mount): do not advertise it.
        primary.write("shared/ghost.md", "unreachable\n")
        primary.write("notes/real.md", "reachable\n")
        payload = json.loads(ro_tools.list_files(recursive=True))
        paths = {e["path"] for e in payload["files"]}
        assert "shared/ghost.md" not in paths
        assert "notes/real.md" in paths
        # The mount entry itself is still there, exactly once.
        assert [e["path"] for e in payload["files"]].count("shared") == 1


class TestSearchAndCheckLines:
    def test_root_search_covers_the_primary_only(self, primary, shared, ro_tools):
        primary.write("notes/a.md", "needle in my own files\n")
        shared.write("notes/b.md", "needle in the mount\n")
        payload = json.loads(ro_tools.search_content("needle"))
        assert [f["file"] for f in payload["files"]] == ["notes/a.md"]

    def test_scoped_search_reaches_the_mount_with_prefixed_paths(self, shared, ro_tools):
        shared.write("notes/b.md", "needle in the mount\n")
        payload = json.loads(ro_tools.search_content("needle", directory="shared"))
        assert [f["file"] for f in payload["files"]] == ["shared/notes/b.md"]
        assert "needle" in ro_tools.read_file(payload["files"][0]["file"])

    def test_scoped_search_within_a_mount_subdirectory(self, shared, ro_tools):
        shared.write("notes/b.md", "needle here\n")
        shared.write("other/c.md", "needle there\n")
        payload = json.loads(ro_tools.search_content("needle", directory="shared/notes"))
        assert [f["file"] for f in payload["files"]] == ["shared/notes/b.md"]

    def test_shadowed_primary_matches_are_dropped_from_search(self, primary, ro_tools):
        primary.write("shared/ghost.md", "needle unreachable\n")
        payload = json.loads(ro_tools.search_content("needle"))
        assert payload["files"] == []

    def test_check_lines_scopes_into_a_mount(self, primary, shared, ro_tools):
        shared.write("seen/log.md", "example.com/a\n")
        primary.write("seen/log.md", "example.com/b\n")
        scoped = json.loads(ro_tools.check_lines(["example.com/a", "example.com/b"], directory="shared"))
        assert scoped["found"] == ["example.com/a"]
        assert scoped["missing"] == ["example.com/b"]
        # Unscoped stays on the primary.
        root = json.loads(ro_tools.check_lines(["example.com/a", "example.com/b"]))
        assert root["found"] == ["example.com/b"]


class TestQuotasStayPerStore:
    def test_write_through_a_mount_charges_the_mounted_quota(self, primary, backend):
        tiny = FileSystem(backend=backend, namespace="tiny", max_file_bytes=10)
        toolkit = primary.tools(mounts={"team": Mount(fs=tiny, mode="rw")})
        result = toolkit.write_file("team/a.md", "0123456789x")
        assert result == (
            "Error: team/a.md would be 11 bytes (limit 10 per file). "
            "Split the topic into smaller files (or partition by date) and retry."
        )
        # The primary's own (default) cap is untouched: the same content fits there.
        assert toolkit.write_file("a.md", "0123456789x").startswith("Wrote 11 bytes")

    def test_mounted_namespace_cap_is_the_mounted_stores(self, primary, backend):
        tiny = FileSystem(backend=backend, namespace="tiny", max_namespace_bytes=10)
        toolkit = primary.tools(mounts={"team": Mount(fs=tiny, mode="rw")})
        toolkit.write_file("team/a.md", "123456")
        result = toolkit.write_file("team/b.md", "78901")
        assert result.startswith("Error: storage is full (6 of 10 bytes).")
        # Primary usage is untouched by mounted writes.
        assert primary.usage().total_bytes == 0


class TestTemplatedMounts:
    """A mounted FileSystem may be templated; it resolves per call from the same
    injected context as the primary, and fails closed the same way."""

    @pytest.fixture
    def per_user_tools(self, backend, primary):
        per_user = FileSystem(backend=backend, namespace="team/{user_id}")
        return backend, primary.tools(mounts={"team": Mount(fs=per_user, mode="rw")})

    def test_mounted_template_resolves_per_call(self, per_user_tools):
        from agno.run import RunContext

        backend, toolkit = per_user_tools
        ctx_a = RunContext(run_id="r1", session_id="s1", user_id="alice")
        ctx_b = RunContext(run_id="r2", session_id="s2", user_id="bob")
        toolkit.write_file("team/a.md", "alice's", run_context=ctx_a)
        toolkit.write_file("team/a.md", "bob's", run_context=ctx_b)
        assert backend.read("team/alice", "a.md") == "alice's"
        assert backend.read("team/bob", "a.md") == "bob's"
        assert "alice" in toolkit.read_file("team/a.md", run_context=ctx_a)

    def test_mounted_template_fails_closed_without_identity(self, per_user_tools):
        _backend, toolkit = per_user_tools
        expected = "Error: this agent's files require user_id for this run and none was provided."
        assert toolkit.read_file("team/a.md") == expected
        assert toolkit.write_file("team/a.md", "x") == expected
        assert toolkit.list_files(directory="team") == expected

    def test_untemplated_primary_still_works_beside_a_templated_mount(self, primary, per_user_tools):
        _backend, toolkit = per_user_tools
        assert toolkit.write_file("notes/a.md", "mine").startswith("Wrote")
        assert primary.read("notes/a.md") == "mine"


class TestSurfaceUnchanged:
    """Mounts add zero model-facing surface: same tools, same schemas, no new params."""

    def test_tool_names_identical_with_and_without_mounts(self, primary, shared):
        plain = primary.tools()
        mounted = primary.tools(mounts={"shared": shared})
        assert list(mounted.functions.keys()) == list(plain.functions.keys())
        assert list(mounted.async_functions.keys()) == list(plain.async_functions.keys())

    def test_schemas_identical_with_and_without_mounts(self, primary, shared):
        plain = primary.tools(include_tools=FileSystemTools.FULL_TOOLS)
        mounted = primary.tools(include_tools=FileSystemTools.FULL_TOOLS, mounts={"shared": shared})
        for name in FileSystemTools.FULL_TOOLS:
            plain_fn, mounted_fn = plain.functions[name], mounted.functions[name]
            plain_fn.process_entrypoint()
            mounted_fn.process_entrypoint()
            assert mounted_fn.parameters == plain_fn.parameters
            properties = mounted_fn.parameters.get("properties", {})
            assert "namespace" not in properties
            assert "mount" not in properties

    def test_read_only_toolkit_accepts_mounts(self, primary, shared):
        toolkit = primary.tools(read_only=True, mounts={"shared": shared})
        assert list(toolkit.functions.keys()) == FileSystemTools.READ_ONLY_TOOLS
        shared.write("a.md", "x\n")
        assert "1\tx" in toolkit.read_file("shared/a.md")


class TestInstructions:
    def test_instructions_name_each_mount_and_its_mode(self, primary, shared):
        text = FileSystem.instructions(mounts={"shared": shared, "team": Mount(fs=shared, mode="rw")})
        assert "shared/ (read-only)" in text
        assert "team/ (read-write)" in text
        assert "shared mounts" in text
        assert "cannot write, move or delete inside a read-only mount" in text

    def test_all_rw_mounts_skip_the_read_only_line(self, shared):
        text = FileSystem.instructions(mounts={"team": Mount(fs=shared, mode="rw")})
        assert "team/ (read-write)" in text
        assert "read-only mount" not in text

    def test_no_mounts_leaves_the_text_unchanged(self):
        assert FileSystem.instructions(mounts=None) == FileSystem.instructions()
        assert FileSystem.instructions(mounts={}) == FileSystem.instructions()

    def test_toolkit_default_instructions_carry_the_mount_line(self, primary, shared):
        toolkit = primary.tools(mounts={"shared": shared})
        assert toolkit.instructions == FileSystem.instructions(mounts={"shared": shared})
        assert "shared/ (read-only)" in toolkit.instructions

    def test_explicit_instructions_are_respected(self, primary, shared):
        toolkit = primary.tools(mounts={"shared": shared}, instructions="my own text")
        assert toolkit.instructions == "my own text"

    def test_mount_conventions_keep_the_one_line_bullet_shape(self, shared):
        # Composed into an agent's instructions list the block renders as one
        # bullet; every convention, including the mount lines, must stay one
        # indented line (test_toolkit.py::test_every_bullet_is_one_line_and_nests).
        text = FileSystem.instructions(mounts={"shared": shared})
        body = text.split("Conventions:\n", 1)[1]
        for line in body.split("\n"):
            if line:
                assert line.startswith("  - "), line

    def test_namespace_still_never_appears(self, shared):
        # The mounted store's namespace is "global"; only the mount NAME may show.
        text = FileSystem.instructions(mounts={"shared": shared})
        assert "global" not in text
        assert "namespace" not in text.lower()


class TestAsyncTwins:
    @pytest.mark.asyncio
    async def test_async_write_and_read_through_a_mount(self, shared, rw_tools):
        assert (await rw_tools.awrite_file("team/a.md", "async hello")).startswith("Wrote")
        assert shared.read("a.md") == "async hello"
        assert "async hello" in await rw_tools.aread_file("team/a.md")

    @pytest.mark.asyncio
    async def test_async_ro_enforcement(self, shared, ro_tools):
        assert await ro_tools.aappend_file("shared/log.md", "rec-1") == RO_ERROR
        assert shared.read("log.md") is None
