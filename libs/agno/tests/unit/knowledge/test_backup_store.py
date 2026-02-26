"""Tests for BackupStore."""

import json
import tempfile
from pathlib import Path

import pytest

from agno.knowledge.store.backup_store import BackupStore, GrepResult


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def store(tmp_dir):
    return BackupStore(base_dir=tmp_dir)


class TestStore:
    def test_store_creates_directory_and_files(self, store, tmp_dir):
        store.store(
            content_id="doc1",
            parsed_text="Hello world\nLine 2",
            metadata={"name": "test.pdf"},
        )

        content_dir = Path(tmp_dir) / "doc1"
        assert content_dir.exists()
        assert (content_dir / "parsed.txt").exists()
        assert (content_dir / "metadata.json").exists()

        parsed = (content_dir / "parsed.txt").read_text()
        assert parsed == "Hello world\nLine 2"

        meta = json.loads((content_dir / "metadata.json").read_text())
        assert meta["name"] == "test.pdf"

    def test_store_with_raw_bytes(self, store, tmp_dir):
        store.store(
            content_id="doc2",
            parsed_text="content",
            raw_bytes=b"raw pdf data",
            file_extension=".pdf",
        )

        raw_path = Path(tmp_dir) / "doc2" / "raw.pdf"
        assert raw_path.exists()
        assert raw_path.read_bytes() == b"raw pdf data"

    def test_store_extension_normalization(self, store, tmp_dir):
        store.store(
            content_id="doc3",
            parsed_text="content",
            raw_bytes=b"data",
            file_extension="txt",
        )

        raw_path = Path(tmp_dir) / "doc3" / "raw.txt"
        assert raw_path.exists()

    @pytest.mark.asyncio
    async def test_astore(self, store, tmp_dir):
        await store.astore(
            content_id="doc4",
            parsed_text="async content",
        )

        parsed = (Path(tmp_dir) / "doc4" / "parsed.txt").read_text()
        assert parsed == "async content"


class TestRead:
    def test_read_full_document(self, store):
        store.store("doc1", "Line 1\nLine 2\nLine 3\nLine 4\nLine 5")

        result = store.read("doc1")
        assert result is not None
        assert "[Lines 1-5 of 5]" in result
        assert "1: Line 1" in result
        assert "5: Line 5" in result

    def test_read_with_pagination(self, store):
        lines = "\n".join(f"Line {i}" for i in range(1, 11))
        store.store("doc1", lines)

        result = store.read("doc1", offset=3, limit=4)
        assert result is not None
        assert "[Lines 4-7 of 10]" in result
        assert "4: Line 4" in result
        assert "7: Line 7" in result

    def test_read_nonexistent_returns_none(self, store):
        assert store.read("nonexistent") is None

    @pytest.mark.asyncio
    async def test_aread(self, store):
        store.store("doc1", "content")
        result = await store.aread("doc1")
        assert result is not None


class TestGrep:
    def test_grep_finds_pattern(self, store):
        store.store("doc1", "apple\nbanana\ncherry\ndate\nelderberry")

        results = store.grep("doc1", "cherry")
        assert len(results) == 1
        assert results[0].line_number == 3
        assert results[0].line == "cherry"

    def test_grep_with_context(self, store):
        store.store("doc1", "line1\nline2\nmatch\nline4\nline5")

        results = store.grep("doc1", "match", context=1)
        assert len(results) == 1
        assert results[0].context_before == ["line2"]
        assert results[0].context_after == ["line4"]

    def test_grep_regex(self, store):
        store.store("doc1", "foo123\nbar456\nbaz789")

        results = store.grep("doc1", r"\d{3}")
        assert len(results) == 3

    def test_grep_max_matches(self, store):
        store.store("doc1", "\n".join(f"match {i}" for i in range(50)))

        results = store.grep("doc1", "match", max_matches=5)
        assert len(results) == 5

    def test_grep_invalid_regex(self, store):
        store.store("doc1", "content")
        results = store.grep("doc1", "[invalid")
        assert results == []

    def test_grep_nonexistent_document(self, store):
        results = store.grep("nonexistent", "pattern")
        assert results == []

    @pytest.mark.asyncio
    async def test_agrep(self, store):
        store.store("doc1", "findme\nignore")
        results = await store.agrep("doc1", "findme")
        assert len(results) == 1


class TestGrepAll:
    def test_grep_all_searches_multiple_docs(self, store):
        store.store("doc1", "apple pie\norange juice")
        store.store("doc2", "apple sauce\ngrape soda")

        results = store.grep_all("apple")
        assert len(results) == 2
        content_ids = [r.content_id for r in results]
        assert "doc1" in content_ids
        assert "doc2" in content_ids

    def test_grep_all_max_matches(self, store):
        store.store("doc1", "match\nmatch\nmatch")
        store.store("doc2", "match\nmatch")

        results = store.grep_all("match", max_matches=3)
        assert len(results) == 3

    def test_grep_all_empty_store(self, store):
        results = store.grep_all("pattern")
        assert results == []


class TestGetTools:
    def test_get_tools_returns_two_tools(self, store):
        tools = store.get_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "read_backup" in names
        assert "grep_backup" in names

    def test_read_backup_tool(self, store):
        store.store("doc1", "hello world")
        tools = store.get_tools()
        read_tool = next(t for t in tools if t.name == "read_backup")
        result = read_tool.entrypoint("doc1")
        assert "hello world" in result

    def test_read_backup_not_found(self, store):
        tools = store.get_tools()
        read_tool = next(t for t in tools if t.name == "read_backup")
        result = read_tool.entrypoint("missing")
        assert "not found" in result

    def test_grep_backup_tool(self, store):
        store.store("doc1", "findme\nignore")
        tools = store.get_tools()
        grep_tool = next(t for t in tools if t.name == "grep_backup")
        result = grep_tool.entrypoint("findme", content_id="doc1")
        assert "findme" in result

    def test_grep_backup_no_matches(self, store):
        store.store("doc1", "nothing here")
        tools = store.get_tools()
        grep_tool = next(t for t in tools if t.name == "grep_backup")
        result = grep_tool.entrypoint("xyz")
        assert "No matches found" in result


class TestGrepResultFormat:
    def test_to_str(self):
        result = GrepResult(
            content_id="doc1",
            line_number=5,
            line="matched line",
            context_before=["before1", "before2"],
            context_after=["after1"],
        )
        formatted = result.to_str()
        assert "before1" in formatted
        assert "before2" in formatted
        assert "5: matched line" in formatted
        assert "after1" in formatted
