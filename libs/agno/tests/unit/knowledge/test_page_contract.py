import asyncio
import copy
import dataclasses
import inspect
import threading

import pytest

from agno.db.sqlite import SqliteDb
from agno.fs.errors import InvalidPathError
from agno.knowledge._page_source import page_path
from agno.knowledge.knowledge import Knowledge
from agno.utils.bounded import BoundedWorkers


def test_constructor_preserves_positional_fields_and_keyword_only_page_store():
    first, second = SqliteDb(), SqliteDb()
    knowledge = Knowledge("docs", None, None, first, 5)
    assert knowledge.contents_db is first and knowledge.max_results == 5
    assert dataclasses.replace(knowledge, contents_db=second).contents_db is second
    assert copy.copy(knowledge).contents_db is first
    assert Knowledge(**{f.name: getattr(knowledge, f.name) for f in dataclasses.fields(knowledge)}).contents_db is first
    assert inspect.signature(Knowledge).parameters["page_store"].kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError):
        Knowledge("docs", None, None, first, 5, None, None, False, 0, 1.0, None)


@pytest.mark.asyncio
async def test_page_legacy_search_and_retrieve_use_published_chunks_without_expansion(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from agno.knowledge.page import SearchHit, SearchResult, SearchUnavailable

    knowledge = Knowledge(max_results=3)
    knowledge.page_store = object()
    result = SearchResult(
        results=(
            SearchHit(
                path="/page.md",
                url="https://example.com/page",
                title="Page",
                revision="published",
                chunk_id="chunk",
                content="Ranked excerpt",
                score=0.7,
                rank=1,
            ),
        )
    )
    search = Mock(return_value=result)
    asearch = AsyncMock(return_value=result)
    monkeypatch.setattr(knowledge, "search_pages", search)
    monkeypatch.setattr(knowledge, "asearch_pages", asearch)
    monkeypatch.setattr(knowledge, "read_page", Mock(side_effect=AssertionError("unexpected expansion")))
    monkeypatch.setattr(knowledge, "aread_page", AsyncMock(side_effect=AssertionError("unexpected expansion")))
    for method in (knowledge.search, knowledge.retrieve):
        docs = method("query", user_id="shared-reader")
        assert len(docs) == 1 and docs[0].content == "Ranked excerpt"
        assert docs[0].meta_data["revision"] == "published"
        with pytest.raises(ValueError, match="filters"):
            method("query", filters={"name": "private"})
    for method in (knowledge.asearch, knowledge.aretrieve):
        docs = await method("query", max_results=2, user_id="shared-reader")
        assert len(docs) == 1 and docs[0].content == "Ranked excerpt"
        assert docs[0].meta_data["revision"] == "published"
        with pytest.raises(ValueError, match="filters"):
            await method("query", filters={"name": "private"})
    assert search.call_count == asearch.await_count == 2
    search.assert_called_with("query", limit=3)
    asearch.assert_awaited_with("query", limit=2)
    assert [tool.name for tool in knowledge.get_tools()] == ["search_knowledge_base"]
    assert [tool.name for tool in await knowledge.aget_tools()] == ["search_knowledge_base"]
    with pytest.raises(ValueError, match="filters"):
        knowledge.get_tools(enable_agentic_filters=True)
    search.side_effect = SearchUnavailable()
    asearch.side_effect = SearchUnavailable()
    with pytest.raises(SearchUnavailable):
        knowledge.retrieve("query")
    with pytest.raises(SearchUnavailable):
        await knowledge.aretrieve("query")


@pytest.mark.parametrize(
    "path", ["/../secret", "/a%2fb", "/a%5Cb", "/a%252fb", "/a\\b", "/a//b", "/a\x00b", "/a%xx", "/%2e%2e/a"]
)
def test_page_paths_fail_closed(path):
    with pytest.raises((ValueError, InvalidPathError)):
        page_path(path)


def test_page_path_normalization():
    assert page_path("/") == "/index.md"
    assert page_path("/cafe\u0301") == "/café.md"
    assert page_path("/a.md") == "/a.md"


@pytest.mark.asyncio
async def test_cancelled_worker_retains_capacity_until_actual_exit():
    workers = BoundedWorkers(1, "test-page-worker")
    entered, release = threading.Event(), threading.Event()

    def operation(*, budget):
        entered.set()
        release.wait(2)
        budget.remaining()

    task = asyncio.create_task(workers.run(operation, seconds=5))
    while not entered.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(TimeoutError, match="worker_capacity"):
        await workers.run(operation, seconds=5)
    release.set()


def test_discovery_nested_cycles_and_fumadocs_normalization(monkeypatch):
    from agno.knowledge._page_source import PageSource
    from agno.utils.bounded import WorkBudget

    base = "https://docs.example.com/docs"
    site = {
        base + "/llms.txt": "- [Home](" + base + "/llms.mdx/docs)\n- [SDK](" + base + "/_llms/sdk.md)",
        base + "/_llms/sdk.md": "- [Agent](" + base + "/agents.md)\n- [Loop](" + base + "/llms.txt)",
    }
    seen = []

    def fetch(self, url, max_bytes):
        seen.append(url)
        return site[url]

    monkeypatch.setattr(PageSource, "fetch", fetch)
    source = PageSource(base + "/llms.txt", None, WorkBudget(5))
    pages = source.discover()
    assert source.complete and len(seen) == 2
    assert pages["/index.md"].url == base + "/index.md"
    assert pages["/index.md"].citation_url == base + "/"
    assert pages["/agents.md"].url == base + "/agents.md"


def test_collisions_and_foreign_destinations_cannot_prune(monkeypatch):
    from agno.knowledge._page_source import PageSource
    from agno.utils.bounded import WorkBudget

    base = "https://docs.example.com"
    index = "\n".join(
        [
            "- [A](" + base + "/a.md)",
            "- [First](" + base + "/café.md)",
            "- [Second](" + base + "/cafe%CC%81.md)",
            "- [Foreign](https://elsewhere.example/x.md)",
        ]
    )
    monkeypatch.setattr(PageSource, "fetch", lambda *args: index)
    source = PageSource(base + "/llms.txt", None, WorkBudget(5))
    pages = source.discover()
    assert not source.complete and set(pages) == {"/a.md"}
