"""Unit tests for the BaseFS base emulations (spec D3) against a minimal backend."""

import asyncio
from typing import Dict, List, Optional, Tuple

import pytest

from agno.fs._paths import path_in_directory
from agno.fs.base import BaseFS
from agno.fs.errors import QuotaExceededError, UnsupportedOperationError
from agno.fs.types import FileMeta

NS = "ns"


class DictBackend(BaseFS):
    """Minimal backend implementing only the required core — everything else emulated."""

    def __init__(self) -> None:
        self.files: Dict[Tuple[str, str], str] = {}

    def read(self, namespace: str, path: str) -> Optional[str]:
        return self.files.get((namespace, path))

    def write(self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None) -> FileMeta:
        if expected_version is not None:
            raise UnsupportedOperationError(
                "DictBackend does not version files", operation="write", backend="DictBackend"
            )
        self.files[(namespace, path)] = content
        return FileMeta(path=path, size_bytes=len(content.encode("utf-8")), version=None, updated_at=None)

    def list(self, namespace: str, directory: str = "") -> List[FileMeta]:
        return [
            FileMeta(path=path, size_bytes=len(content.encode("utf-8")), version=None, updated_at=None)
            for (ns, path), content in self.files.items()
            if ns == namespace and path_in_directory(path, directory)
        ]

    def delete(self, namespace: str, path: str) -> bool:
        return self.files.pop((namespace, path), None) is not None


@pytest.fixture
def backend() -> DictBackend:
    return DictBackend()


class TestAppendEmulation:
    def test_creates_missing_file(self, backend):
        meta = backend.append(NS, "a.md", "x\n")
        assert backend.read(NS, "a.md") == "x\n"
        assert meta.size_bytes == 2

    def test_separator_only_when_needed(self, backend):
        backend.write(NS, "a.md", "one")  # no trailing newline
        backend.append(NS, "a.md", "two\n")
        assert backend.read(NS, "a.md") == "one\ntwo\n"
        backend.append(NS, "a.md", "three\n")
        assert backend.read(NS, "a.md") == "one\ntwo\nthree\n"

    def test_no_leading_blank_line_on_empty_file(self, backend):
        backend.write(NS, "a.md", "")
        backend.append(NS, "a.md", "x\n")
        assert backend.read(NS, "a.md") == "x\n"

    def test_crlf_normalized_via_shared_transform(self, backend):
        backend.append(NS, "a.md", "one\r\ntwo\r\n")
        assert backend.read(NS, "a.md") == "one\ntwo\n"

    def test_empty_chunk_is_noop(self, backend):
        meta = backend.append(NS, "a.md", "\r\n\n")
        assert meta.size_bytes == 0
        assert backend.read(NS, "a.md") is None
        assert backend.files == {}

    def test_max_file_bytes_best_effort(self, backend):
        backend.write(NS, "a.md", "12345\n")
        with pytest.raises(QuotaExceededError) as excinfo:
            backend.append(NS, "a.md", "678901", max_file_bytes=10)
        assert excinfo.value.scope == "file"
        assert excinfo.value.limit == 10
        assert backend.read(NS, "a.md") == "12345\n"


class TestMoveEmulation:
    def test_move(self, backend):
        backend.write(NS, "a.md", "x")
        meta = backend.move(NS, "a.md", "b.md")
        assert meta.path == "b.md"
        assert backend.read(NS, "a.md") is None
        assert backend.read(NS, "b.md") == "x"

    def test_missing_src(self, backend):
        with pytest.raises(FileNotFoundError):
            backend.move(NS, "missing.md", "b.md")

    def test_dst_exists(self, backend):
        backend.write(NS, "a.md", "x")
        backend.write(NS, "b.md", "y")
        with pytest.raises(FileExistsError):
            backend.move(NS, "a.md", "b.md")

    def test_overwrite(self, backend):
        backend.write(NS, "a.md", "x")
        backend.write(NS, "b.md", "y")
        backend.move(NS, "a.md", "b.md", overwrite=True)
        assert backend.read(NS, "b.md") == "x"


class TestSearchEmulation:
    def test_snippet_window_and_ellipses(self, backend):
        content = ("a" * 300) + "NEEDLE" + ("b" * 300)
        backend.write(NS, "big.md", content)
        matches = backend.search(NS, "needle")
        assert len(matches) == 1
        snippet = matches[0].snippet
        assert snippet.startswith("...")
        assert snippet.endswith("...")
        assert "NEEDLE" in snippet
        # +-200 chars around the match, plus the two ellipsis markers.
        assert len(snippet) == 3 + 200 + 6 + 200 + 3

    def test_snippet_no_ellipsis_at_boundaries(self, backend):
        backend.write(NS, "small.md", "hello world")
        matches = backend.search(NS, "world")
        assert matches[0].snippet == "hello world"

    def test_limit_and_directory_scope(self, backend):
        backend.write(NS, "seen/a.md", "needle")
        backend.write(NS, "seen-old/b.md", "needle")
        matches = backend.search(NS, "needle", directory="seen")
        assert [m.path for m in matches] == ["seen/a.md"]

    def test_empty_query_returns_empty(self, backend):
        backend.write(NS, "a.md", "x")
        assert backend.search(NS, "") == []


class TestContainsEmulation:
    def test_superstring_no_false_positive(self, backend):
        backend.write(NS, "log.md", "example.com/ab\n")
        assert backend.contains(NS, ["example.com/a"]) == set()

    def test_last_line_without_trailing_newline(self, backend):
        backend.write(NS, "log.md", "a\nb")
        assert backend.contains(NS, ["b"]) == {"b"}

    def test_crlf_written_content_is_not_matched(self, backend):
        # A file written with CRLF via write() stores those bytes verbatim; the
        # exact-line check must agree byte-for-byte with the DB padded predicate,
        # which does not match "x\r\n" for the record "x".
        backend.write(NS, "log.md", "x\r\ny\n")
        assert backend.contains(NS, ["x"]) == set()
        assert backend.contains(NS, ["y"]) == {"y"}

    def test_cross_file_and_directory_scope(self, backend):
        backend.write(NS, "seen/a.md", "one\n")
        backend.write(NS, "notes/b.md", "two\n")
        assert backend.contains(NS, ["one", "two"]) == {"one", "two"}
        assert backend.contains(NS, ["one", "two"], directory="seen") == {"one"}

    def test_empty_lines_no_calls(self, backend):
        assert backend.contains(NS, []) == set()


class TestUsageEmulation:
    def test_usage_sums_bytes(self, backend):
        backend.write(NS, "a.md", "12345")
        backend.write(NS, "b.md", "\U0001f600")  # 4 bytes
        result = backend.usage(NS)
        assert result.file_count == 2
        assert result.total_bytes == 9

    def test_empty_namespace(self, backend):
        result = backend.usage("nothing-here")
        assert result.file_count == 0
        assert result.total_bytes == 0


class TestAsyncTwins:
    def test_async_twins_smoke(self, backend):
        async def flow():
            await backend.awrite(NS, "a.md", "hello\n")
            assert await backend.aread(NS, "a.md") == "hello\n"
            await backend.aappend(NS, "log.md", "one\n")
            assert await backend.acontains(NS, ["one"]) == {"one"}
            assert {m.path for m in await backend.alist(NS)} == {"a.md", "log.md"}
            assert len(await backend.asearch(NS, "hello")) == 1
            await backend.amove(NS, "a.md", "b.md")
            usage = await backend.ausage(NS)
            assert usage.file_count == 2
            assert await backend.adelete(NS, "b.md") is True

        asyncio.run(flow())
