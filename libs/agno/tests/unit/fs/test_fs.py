"""Unit tests for the FileSystem programmatic API (spec D2) over LocalFileSystem."""

import asyncio

import pytest

from agno.fs import DEFAULT_NAMESPACE, FileSystem
from agno.fs.errors import InvalidPathError, QuotaExceededError, UnsupportedOperationError
from agno.fs.local import LocalFileSystem


@pytest.fixture
def local_backend(tmp_path) -> LocalFileSystem:
    return LocalFileSystem(root=tmp_path)


@pytest.fixture
def fs(local_backend) -> FileSystem:
    return FileSystem(backend=local_backend, namespace="radar")


class TestEdgeBehaviors:
    def test_read_missing_returns_none(self, fs):
        assert fs.read("missing.md") is None

    def test_read_empty_file_returns_empty_string(self, fs):
        fs.write("empty.md", "")
        assert fs.read("empty.md") == ""

    def test_usage_of_empty_namespace(self, fs):
        result = fs.usage()
        assert result.file_count == 0
        assert result.total_bytes == 0

    def test_contains_empty_input_short_circuits(self, local_backend):
        class NoContainsBackend(LocalFileSystem):
            def contains(self, namespace, lines, directory=""):
                raise AssertionError("backend.contains must not be called for an empty input")

        fs = FileSystem(backend=NoContainsBackend(root=local_backend.root), namespace="radar")
        assert fs.contains([]).found == []
        assert fs.contains([]).missing == []
        # Empty after normalization also short-circuits.
        result = fs.contains(["", "\r\n", "\n"])
        assert result.found == [] and result.missing == []

    def test_append_empty_is_noop_and_does_not_create(self, fs):
        meta = fs.append("seen/log.md", "")
        assert meta.size_bytes == 0
        assert meta.version is None
        assert fs.read("seen/log.md") is None
        assert fs.append("seen/log.md", "\n\r\n").size_bytes == 0
        assert fs.read("seen/log.md") is None

    def test_append_empty_on_existing_file_is_noop(self, fs):
        fs.append("seen/log.md", "one\n")
        before = fs.read("seen/log.md")
        meta = fs.append("seen/log.md", "")
        assert fs.read("seen/log.md") == before
        assert meta.size_bytes == len(before.encode("utf-8"))
        assert meta.path == "seen/log.md"

    def test_list_sorted_by_path_segments(self, fs):
        # The three paths that collate differently in Postgres (spec D2).
        fs.write("seen/a.md", "1")
        fs.write("seen.md", "2")
        fs.write("seen-old/a.md", "3")
        assert [m.path for m in fs.list()] == ["seen/a.md", "seen-old/a.md", "seen.md"]

    def test_write_overwrite_false_raises_builtin(self, fs):
        fs.write("a.md", "x")
        with pytest.raises(FileExistsError):
            fs.write("a.md", "y", overwrite=False)
        assert fs.read("a.md") == "x"

    def test_write_overwrite_false_on_missing_file_ok(self, fs):
        fs.write("a.md", "x", overwrite=False)
        assert fs.read("a.md") == "x"

    def test_expected_version_unsupported_on_local(self, fs):
        fs.write("a.md", "x")
        with pytest.raises(UnsupportedOperationError):
            fs.write("a.md", "y", expected_version=1)

    def test_version_none_on_local(self, fs):
        assert fs.write("a.md", "x").version is None


class TestRoundTrip:
    """The dedupe regression: one line transform, both sides (spec D6/D13)."""

    def test_append_then_contains_crlf_and_spaces(self, fs):
        fs.append("seen/2026-07-24.md", "  a\r\nb  \r\n")
        result = fs.contains(["  a", "b  "], directory="seen")
        assert result.found == ["  a", "b  "]
        assert result.missing == []

    def test_leading_spaces_preserved(self, fs):
        fs.append("seen/log.md", "  indented record")
        assert fs.contains(["  indented record"]).found == ["  indented record"]
        assert fs.contains(["indented record"]).missing == ["indented record"]

    def test_trailing_spaces_preserved(self, fs):
        fs.append("seen/log.md", "record  \r\n")
        assert fs.contains(["record  "]).found == ["record  "]
        assert fs.contains(["record"]).missing == ["record"]

    def test_crlf_input_matches_lf_storage(self, fs):
        fs.append("seen/log.md", "http://a\r\n")
        assert fs.read("seen/log.md") == "http://a\n"
        assert fs.contains(["http://a"]).found == ["http://a"]
        assert fs.contains(["http://a\r\n"]).found == ["http://a"]

    def test_superstring_no_false_positive(self, fs):
        fs.append("seen/log.md", "example.com/ab\n")
        result = fs.contains(["example.com/a"])
        assert result.missing == ["example.com/a"]

    def test_u2028_stored_as_one_line_and_found(self, fs):
        # The split-choice regression: a splitlines() append would store two
        # rows and return missing forever (spec D9 step 1 / D13).
        fs.append("seen/log.md", "a\u2028b\n")
        assert fs.read("seen/log.md") == "a\u2028b\n"
        assert fs.contains(["a\u2028b"]).found == ["a\u2028b"]

    def test_interior_cr_rejected_at_append(self, fs):
        with pytest.raises(InvalidPathError):
            fs.append("seen/log.md", "a\rb\r")
        assert fs.read("seen/log.md") is None

    def test_missing_files_mean_all_missing(self, fs):
        result = fs.contains(["a", "b"], directory="seen")
        assert result.found == []
        assert result.missing == ["a", "b"]

    def test_order_preserved_with_duplicates(self, fs):
        fs.append("seen/log.md", "b\n")
        result = fs.contains(["z", "b", "z"])
        assert result.found == ["b"]
        assert result.missing == ["z", "z"]


class TestDirectorySemantics:
    @pytest.fixture
    def populated(self, fs):
        fs.append("seen/a.md", "in-seen\n")
        fs.append("seen-old/b.md", "in-seen-old\n")
        fs.append("a_b/c.md", "in-a_b\n")
        fs.append("aXb/c.md", "in-aXb\n")
        return fs

    def test_list_segment_boundary(self, populated):
        assert [m.path for m in populated.list("seen")] == ["seen/a.md"]

    def test_search_segment_boundary(self, populated):
        matches = populated.search("in-", directory="seen")
        assert [m.path for m in matches] == ["seen/a.md"]

    def test_contains_segment_boundary(self, populated):
        result = populated.contains(["in-seen", "in-seen-old"], directory="seen")
        assert result.found == ["in-seen"]
        assert result.missing == ["in-seen-old"]

    def test_underscore_directory_not_a_wildcard(self, populated):
        result = populated.contains(["in-aXb"], directory="a_b")
        assert result.missing == ["in-aXb"]
        assert populated.contains(["in-a_b"], directory="a_b").found == ["in-a_b"]

    def test_dot_means_root_for_directory_params(self, populated):
        assert len(populated.list(".")) == len(populated.list(""))
        assert populated.contains(["in-seen"], directory=".").found == ["in-seen"]

    def test_dot_rejected_inside_file_paths(self, populated):
        with pytest.raises(InvalidPathError):
            populated.read("seen/./a.md")


class TestQuota:
    def test_file_cap_boundary_on_write(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="q", max_file_bytes=10)
        fs.write("a.md", "0123456789")  # exactly at cap
        with pytest.raises(QuotaExceededError) as excinfo:
            fs.write("b.md", "0123456789x")
        assert excinfo.value.scope == "file"
        assert excinfo.value.current == 11
        assert excinfo.value.limit == 10

    def test_file_cap_counts_bytes_not_chars(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="q", max_file_bytes=3)
        with pytest.raises(QuotaExceededError):
            fs.write("a.md", "\U0001f600")  # 1 char, 4 bytes

    def test_file_cap_on_append(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="q", max_file_bytes=10)
        fs.append("a.md", "12345\n")  # 6 bytes
        with pytest.raises(QuotaExceededError) as excinfo:
            fs.append("a.md", "67890\n")  # would be 12
        assert excinfo.value.scope == "file"

    def test_namespace_cap_on_write(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="q", max_namespace_bytes=10)
        fs.write("a.md", "123456")
        with pytest.raises(QuotaExceededError) as excinfo:
            fs.write("b.md", "78901")
        assert excinfo.value.scope == "namespace"
        assert excinfo.value.current == 6
        assert excinfo.value.limit == 10

    def test_namespace_cap_overwrite_uses_delta(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="q", max_namespace_bytes=10)
        fs.write("a.md", "123456789")
        fs.write("a.md", "12345678")  # shrinking is always fine
        fs.write("a.md", "1234567890")  # grow back to exactly the cap

    def test_namespace_cap_on_append_overestimates_separator(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="q", max_namespace_bytes=10)
        fs.append("a.md", "12345\n")  # 6 bytes
        with pytest.raises(QuotaExceededError):
            fs.append("a.md", "678\n")  # 6 + 4 + 1(estimated sep) = 11 > 10


class TestTemplatedNamespaces:
    def test_construction_validates_placeholders(self, local_backend):
        with pytest.raises(InvalidPathError):
            FileSystem(backend=local_backend, namespace="radar/{tenant}")
        with pytest.raises(InvalidPathError):
            FileSystem(backend=local_backend, namespace="radar/{user_id")

    def test_unresolved_programmatic_calls_raise(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="radar/{user_id}")
        for operation in (
            lambda: fs.read("a.md"),
            lambda: fs.write("a.md", "x"),
            lambda: fs.append("a.md", "x"),
            lambda: fs.move("a.md", "b.md"),
            lambda: fs.delete("a.md"),
            lambda: fs.list(),
            lambda: fs.search("x"),
            lambda: fs.contains(["x"]),
            lambda: fs.usage(),
        ):
            with pytest.raises(InvalidPathError):
                operation()

    def test_resolve_binds_and_isolates(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="radar/{user_id}", max_file_bytes=123)
        bound = fs.resolve(user_id="u42")
        assert bound.namespace == "radar/u42"
        assert bound.max_file_bytes == 123
        bound.append("seen/log.md", "x\n")
        other = fs.resolve(user_id="u43")
        assert other.read("seen/log.md") is None
        assert bound.read("seen/log.md") == "x\n"

    def test_resolve_rejects_multi_segment_value(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="radar/{user_id}")
        with pytest.raises(InvalidPathError):
            fs.resolve(user_id="u42/../u43")
        with pytest.raises(InvalidPathError):
            fs.resolve(user_id="a/b")

    def test_partial_resolve_stays_templated(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="{team_id}/{user_id}")
        partial = fs.resolve(user_id="u42")
        assert partial.is_templated
        with pytest.raises(InvalidPathError):
            partial.read("a.md")
        full = partial.resolve(team_id="t1")
        assert full.namespace == "t1/u42"
        full.write("a.md", "ok")
        assert full.read("a.md") == "ok"

    def test_resolve_on_untemplated_returns_self(self, local_backend):
        fs = FileSystem(backend=local_backend, namespace="radar")
        assert fs.resolve(user_id="u42") is fs


class TestSearch:
    def test_empty_query_returns_empty(self, fs):
        fs.write("a.md", "content")
        assert fs.search("") == []
        assert fs.search("   ") == []

    def test_case_insensitive(self, fs):
        fs.write("a.md", "Hello World")
        matches = fs.search("hello")
        assert len(matches) == 1
        assert matches[0].path == "a.md"
        assert "Hello" in matches[0].snippet

    def test_limit(self, fs):
        for i in range(5):
            fs.write(f"f{i}.md", "needle")
        assert len(fs.search("needle", limit=3)) == 3


class TestMoveDelete:
    def test_move_missing_src(self, fs):
        with pytest.raises(FileNotFoundError):
            fs.move("missing.md", "b.md")

    def test_move_dst_exists(self, fs):
        fs.write("a.md", "x")
        fs.write("b.md", "y")
        with pytest.raises(FileExistsError):
            fs.move("a.md", "b.md")

    def test_move_overwrite(self, fs):
        fs.write("a.md", "x")
        fs.write("b.md", "y")
        meta = fs.move("a.md", "b.md", overwrite=True)
        assert meta.path == "b.md"
        assert fs.read("b.md") == "x"

    def test_delete_returns_existed(self, fs):
        fs.write("a.md", "x")
        assert fs.delete("a.md") is True
        assert fs.delete("a.md") is False


class TestAsyncTwins:
    def test_async_smoke_all_operations(self, fs):
        async def flow():
            await fs.awrite("a.md", "hello\n")
            assert await fs.aread("a.md") == "hello\n"
            await fs.aappend("seen/log.md", "one\n")
            assert (await fs.acontains(["one"], directory="seen")).found == ["one"]
            assert [m.path for m in await fs.alist()] == ["a.md", "seen/log.md"]
            assert len(await fs.asearch("hello")) == 1
            await fs.amove("a.md", "b.md")
            assert await fs.aread("b.md") == "hello\n"
            usage = await fs.ausage()
            assert usage.file_count == 2
            assert await fs.adelete("b.md") is True

        asyncio.run(flow())


class TestDefaultNamespace:
    def test_namespace_is_optional_and_defaults(self, local_backend):
        # A simple app should not have to name a store.
        fs = FileSystem(local_backend)
        assert fs.namespace == DEFAULT_NAMESPACE == "default"
        fs.write("a.md", "x")
        assert fs.read("a.md") == "x"

    def test_default_is_a_real_shared_namespace(self, local_backend):
        # Two unnamed FileSystems on one backend share the default store - the
        # documented behavior, and why multi-tenant apps must name one.
        FileSystem(local_backend).write("a.md", "x")
        assert FileSystem(local_backend).read("a.md") == "x"
        assert FileSystem(local_backend, "other").read("a.md") is None


class TestBackendDispatch:
    def test_agno_db_is_wrapped_automatically(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.fs.db import DbFileSystem

        fs = FileSystem(SqliteDb(db_file=f"{tmp_path}/agent.db"))
        assert isinstance(fs.backend, DbFileSystem)
        fs.write("a.md", "x")
        assert fs.read("a.md") == "x"

    def test_basefs_is_used_as_given(self, local_backend):
        assert FileSystem(local_backend).backend is local_backend

    def test_unrecognised_source_raises_with_guidance(self):
        with pytest.raises(TypeError) as exc:
            FileSystem("not-a-backend")
        assert "SqliteDb" in str(exc.value) and "LocalFileSystem" in str(exc.value)

    def test_import_agno_fs_stays_dependency_light(self):
        # The dispatch imports its backend lazily; `import agno.fs` must not drag
        # SQLAlchemy in (spec D1).
        import subprocess
        import sys

        out = subprocess.run(
            [sys.executable, "-c", "import sys, agno.fs; print('sqlalchemy' in sys.modules)"],
            capture_output=True,
            text=True,
        )
        assert out.stdout.strip() == "False", out.stdout


class TestNamespaceSanitization:
    """Namespaces are lowercase, URL-safe identifiers (spec D6)."""

    def test_case_folds_to_one_store(self, local_backend):
        FileSystem(local_backend, namespace="BANK").write("secret.md", "x")
        for spelling in ("bank", "Bank", "BaNk", "BANK"):
            fs = FileSystem(local_backend, namespace=spelling)
            assert fs.namespace == "bank"
            assert fs.read("secret.md") == "x"

    def test_case_folding_closes_the_case_insensitive_fs_alias(self, local_backend):
        # On a case-insensitive filesystem two spellings land on one directory. With
        # folding they are one namespace ON PURPOSE, and a different name stays apart.
        FileSystem(local_backend, namespace="bank").write("secret.md", "TOPSECRET")
        assert FileSystem(local_backend, namespace="other").read("secret.md") is None

    def test_multi_segment_and_templates_fold(self, local_backend):
        assert FileSystem(local_backend, namespace="Radar/User-42").namespace == "radar/user-42"
        templated = FileSystem(local_backend, namespace="Radar/{user_id}")
        assert templated.namespace == "radar/{user_id}"
        assert templated.resolve(user_id="Alice").namespace == "radar/alice"
        assert templated.resolve(user_id="alice").namespace == "radar/alice"

    @pytest.mark.parametrize(
        "raw,encoded",
        [("münchen", "m%c3%bcnchen"), ("my namespace", "my%20namespace"), ("a%b", "a%25b")],
    )
    def test_unsafe_characters_are_encoded_not_rejected(self, local_backend, raw, encoded):
        # Any id must be expressible: rejecting would break the documented
        # namespace="radar/{user_id}" idiom for emails and non-ASCII names.
        fs = FileSystem(local_backend, namespace=raw)
        assert fs.namespace == encoded
        fs.write("a.md", "x")
        assert fs.read("a.md") == "x"

    def test_encoding_is_injective(self, local_backend):
        # The reason to encode rather than slugify: a slug maps "a b" and "a-b"
        # onto one namespace, so two tenants would silently share files.
        names = ["a b", "a-b", "a_b", "a%20b", "a+b"]
        resolved = {FileSystem(local_backend, namespace=n).namespace for n in names}
        assert len(resolved) == len(names)

    def test_file_paths_stay_case_sensitive(self, local_backend):
        # Only the namespace is an identifier; paths keep the D6 grammar.
        fs = FileSystem(local_backend, namespace="n")
        fs.write("Notes/README.md", "x")
        assert [m.path for m in fs.list()] == ["Notes/README.md"]


class TestNamespaceCharset:
    def test_email_ids_resolve(self, local_backend):
        # Ids are commonly emails; rejecting them would break the documented
        # namespace="radar/{user_id}" idiom on day one.
        fs = FileSystem(local_backend, namespace="radar/{user_id}")
        assert fs.resolve(user_id="Alice+Tag@X.com").namespace == "radar/alice+tag@x.com"

    @pytest.mark.parametrize(
        "raw,encoded", [("Ünal", "radar/%c3%bcnal"), ("a b", "radar/a%20b"), ("100%", "radar/100%25")]
    )
    def test_template_values_are_encoded_not_rejected(self, local_backend, raw, encoded):
        fs = FileSystem(local_backend, namespace="radar/{user_id}")
        assert fs.resolve(user_id=raw).namespace == encoded

    def test_adjacent_placeholders_rejected(self, local_backend):
        # (a, bc) and (ab, c) would both resolve to "abc" and share one store.
        with pytest.raises(InvalidPathError):
            FileSystem(local_backend, namespace="{user_id}{team_id}")
        # A separator makes resolution unique again.
        FileSystem(local_backend, namespace="{user_id}-{team_id}")
        FileSystem(local_backend, namespace="{user_id}/{team_id}")
