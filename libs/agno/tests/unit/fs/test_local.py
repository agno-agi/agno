"""Unit tests for LocalFileSystem (spec D5) including the separator matrix (spec D9)."""

import os
import stat

import pytest

from agno.fs.errors import InvalidPathError, QuotaExceededError, UnsupportedOperationError
from agno.fs.local import LocalFileSystem

NS = "test-ns"


@pytest.fixture
def local_fs(tmp_path) -> LocalFileSystem:
    return LocalFileSystem(root=tmp_path)


class TestSeparatorMatrix:
    """Append onto (missing | empty | trailing-newline | no-trailing-newline) x
    chunk (with | without trailing newline) -> intact lines, exact size_bytes.
    Every existing-state column includes a multi-byte last character variant."""

    EXISTING_STATES = {
        "missing": None,
        "empty": "",
        "trailing_newline": "a\n",
        "no_trailing_newline": "a",
        "multibyte_trailing_newline": "hi \U0001f600\n",
        "multibyte_no_trailing_newline": "hi \U0001f600",
    }
    CHUNKS = {"with_trailing_newline": "x\ny\n", "without_trailing_newline": "x\ny"}

    @pytest.mark.parametrize("existing_key", list(EXISTING_STATES.keys()))
    @pytest.mark.parametrize("chunk_key", list(CHUNKS.keys()))
    def test_matrix_cell(self, local_fs, existing_key, chunk_key):
        existing = self.EXISTING_STATES[existing_key]
        chunk = self.CHUNKS[chunk_key]
        path = f"seen/{existing_key}-{chunk_key}.md"
        if existing is not None:
            local_fs.write(NS, path, existing)

        meta = local_fs.append(NS, path, chunk)

        content = local_fs.read(NS, path)
        if existing is None or existing == "":
            expected = "x\ny\n"
        elif existing.endswith("\n"):
            expected = existing + "x\ny\n"
        else:
            expected = existing + "\n" + "x\ny\n"
        assert content == expected
        assert meta.size_bytes == len(expected.encode("utf-8"))
        # No blank line ever appears at a chunk boundary.
        assert "\n\n" not in content

    def test_appended_lines_stay_intact(self, local_fs):
        local_fs.append(NS, "log.md", "one\n")
        local_fs.append(NS, "log.md", "two")
        local_fs.append(NS, "log.md", "three\r\n")
        assert local_fs.read(NS, "log.md") == "one\ntwo\nthree\n"


class TestLocalWrite:
    def test_write_and_read_roundtrip(self, local_fs):
        meta = local_fs.write(NS, "notes/a.md", "hello\n")
        assert meta.path == "notes/a.md"
        assert meta.size_bytes == 6
        assert meta.version is None
        assert local_fs.read(NS, "notes/a.md") == "hello\n"

    def test_no_tmp_file_left_behind(self, local_fs, tmp_path):
        local_fs.write(NS, "a.md", "x")
        leftovers = [p for p in (tmp_path / NS).rglob("*.tmp")]
        assert leftovers == []

    def test_crlf_content_roundtrips_byte_exact(self, local_fs):
        # newline="" everywhere: no universal-newline translation on read or write.
        local_fs.write(NS, "a.md", "x\r\ny\r\n")
        assert local_fs.read(NS, "a.md") == "x\r\ny\r\n"
        meta = [m for m in local_fs.list(NS) if m.path == "a.md"][0]
        assert meta.size_bytes == len("x\r\ny\r\n".encode("utf-8"))

    def test_expected_version_unsupported(self, local_fs):
        local_fs.write(NS, "a.md", "x")
        with pytest.raises(UnsupportedOperationError) as excinfo:
            local_fs.write(NS, "a.md", "y", expected_version=1)
        assert excinfo.value.operation == "write"
        assert excinfo.value.backend == "LocalFileSystem"

    def test_version_is_none(self, local_fs):
        meta = local_fs.write(NS, "a.md", "x")
        assert meta.version is None


class TestLocalFileMode:
    """A file's permissions must not depend on which operation created it."""

    @staticmethod
    def _mode(tmp_path, name: str) -> int:
        return stat.S_IMODE((tmp_path / NS / name).stat().st_mode)

    def test_write_and_append_create_the_same_mode(self, local_fs, tmp_path):
        local_fs.write(NS, "written.md", "x")
        local_fs.append(NS, "appended.md", "y")
        assert self._mode(tmp_path, "written.md") == 0o600
        assert self._mode(tmp_path, "appended.md") == 0o600

    def test_append_leaves_an_existing_files_mode_alone(self, local_fs, tmp_path):
        local_fs.write(NS, "a.md", "x")
        os.chmod(tmp_path / NS / "a.md", 0o644)
        local_fs.append(NS, "a.md", "y")
        assert self._mode(tmp_path, "a.md") == 0o644
        assert local_fs.read(NS, "a.md") == "x\ny\n"


class TestLocalPathCollapse:
    def test_trailing_dot_rejected_not_collapsed(self, local_fs):
        # safe_join_relative_path would strip the trailing dot and silently collapse
        # "notes/report." onto "notes/report" — a non-injective map that also enables a
        # cross-namespace collapse. LocalFileSystem now rejects any name the on-disk map
        # would alter, so its legal set is a true strict subset of D6 (spec D5).
        local_fs.write(NS, "notes/report", "second")
        with pytest.raises(InvalidPathError):
            local_fs.write(NS, "notes/report.", "first")
        with pytest.raises(InvalidPathError):
            local_fs.read(NS, "notes/report.")

    def test_fullwidth_dot_traversal_rejected(self, local_fs):
        # Fullwidth dots are NFC-stable so D6 accepts them, but safe_join NFKC-folds
        # them to ".." — a traversal escape. Must be rejected, not remapped.
        local_fs.write("bank", "secret.md", "TOPSECRET")
        with pytest.raises(InvalidPathError):
            local_fs.read(NS, "．．/bank/secret.md")

    def test_compat_variant_namespace_rejected(self, local_fs):
        # Ligature "ﬀ" NFKC-folds to "ff"; rejecting it keeps distinct tenants isolated.
        local_fs.write("ff", "s.md", "ff-data")
        with pytest.raises(InvalidPathError):
            local_fs.write("ﬀ", "s.md", "collision")

    def test_windows_drive_prefix_rejected_by_containment(self, local_fs):
        with pytest.raises(InvalidPathError):
            local_fs.write(NS, "C:/x", "data")

    def test_windows_reserved_name_rejected(self, local_fs):
        with pytest.raises(InvalidPathError):
            local_fs.write(NS, "CON", "data")


class TestLocalAppendCap:
    def test_append_cap_best_effort(self, local_fs):
        local_fs.write(NS, "a.md", "12345\n")
        with pytest.raises(QuotaExceededError) as excinfo:
            local_fs.append(NS, "a.md", "6789", max_file_bytes=10)
        assert excinfo.value.scope == "file"
        assert excinfo.value.current == 11
        assert excinfo.value.limit == 10
        assert local_fs.read(NS, "a.md") == "12345\n"

    def test_append_at_cap_passes(self, local_fs):
        local_fs.write(NS, "a.md", "12345\n")
        meta = local_fs.append(NS, "a.md", "6789\n", max_file_bytes=11)
        assert meta.size_bytes == 11

    def test_new_file_over_cap_rejected(self, local_fs):
        with pytest.raises(QuotaExceededError):
            local_fs.append(NS, "new.md", "0123456789", max_file_bytes=5)
        assert local_fs.read(NS, "new.md") is None


class TestLocalMoveDelete:
    def test_move(self, local_fs):
        local_fs.write(NS, "a.md", "x")
        meta = local_fs.move(NS, "a.md", "b/c.md")
        assert meta.path == "b/c.md"
        assert local_fs.read(NS, "a.md") is None
        assert local_fs.read(NS, "b/c.md") == "x"

    def test_move_missing_src(self, local_fs):
        with pytest.raises(FileNotFoundError):
            local_fs.move(NS, "missing.md", "b.md")

    def test_move_dst_exists(self, local_fs):
        local_fs.write(NS, "a.md", "x")
        local_fs.write(NS, "b.md", "y")
        with pytest.raises(FileExistsError):
            local_fs.move(NS, "a.md", "b.md")
        assert local_fs.read(NS, "b.md") == "y"

    def test_move_overwrite(self, local_fs):
        local_fs.write(NS, "a.md", "x")
        local_fs.write(NS, "b.md", "y")
        local_fs.move(NS, "a.md", "b.md", overwrite=True)
        assert local_fs.read(NS, "b.md") == "x"

    def test_delete_idempotent(self, local_fs):
        local_fs.write(NS, "a.md", "x")
        assert local_fs.delete(NS, "a.md") is True
        assert local_fs.delete(NS, "a.md") is False


class TestLocalListAndIsolation:
    def test_list_scoped_to_directory_at_segment_boundary(self, local_fs):
        local_fs.write(NS, "seen/a.md", "1")
        local_fs.write(NS, "seen-old/b.md", "2")
        local_fs.write(NS, "seen.md", "3")
        paths = {m.path for m in local_fs.list(NS, "seen")}
        assert paths == {"seen/a.md"}

    def test_list_missing_namespace_is_empty(self, local_fs):
        assert local_fs.list("no-such-ns") == []

    def test_namespace_isolation(self, local_fs):
        local_fs.write("ns-a", "f.md", "a")
        local_fs.write("ns-b", "f.md", "b")
        assert local_fs.read("ns-a", "f.md") == "a"
        assert local_fs.read("ns-b", "f.md") == "b"
        assert {m.path for m in local_fs.list("ns-a")} == {"f.md"}

    def test_multi_segment_namespace(self, local_fs):
        local_fs.write("radar/u42", "f.md", "x")
        assert local_fs.read("radar/u42", "f.md") == "x"
        assert local_fs.read("radar/u43", "f.md") is None

    def test_parent_namespace_does_not_leak_child_namespace(self, local_fs):
        # A child namespace must not surface inside its name-prefix parent — on disk
        # the namespace is one percent-encoded component, so "radar" and "radar/alice"
        # are siblings, not nested. Regression for the flatten-collision leak.
        local_fs.write("radar/alice", "secret.md", "private")
        local_fs.write("radar", "own.md", "mine")
        assert {m.path for m in local_fs.list("radar")} == {"own.md"}
        assert local_fs.read("radar", "alice/secret.md") is None
        assert local_fs.delete("radar", "alice/secret.md") is False
        assert local_fs.read("radar/alice", "secret.md") == "private"


class TestSelfMoveParity:
    def test_self_move_is_a_noop_not_a_collision(self, local_fs):
        # DbFileSystem and the base emulation both succeed on move(a, a); Local used
        # to raise FileExistsError from its dst-exists check, so the two v1 backends
        # answered the same model-reachable call differently (PR review).
        local_fs.write(NS, "notes/a.md", "x")
        meta = local_fs.move(NS, "notes/a.md", "notes/a.md")
        assert meta.path == "notes/a.md"
        assert local_fs.read(NS, "notes/a.md") == "x"
