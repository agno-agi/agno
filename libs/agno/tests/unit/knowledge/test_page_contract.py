import asyncio
import copy
import dataclasses
import threading

import pytest

from agno.db.sqlite import SqliteDb
from agno.fs.errors import InvalidPathError
from agno.knowledge._page_source import page_path
from agno.knowledge.knowledge import Knowledge
from agno.utils.bounded import BoundedWorkers


def test_database_alias_keeps_positional_fields_and_dataclass_replacement():
    first, second = SqliteDb(), SqliteDb()
    knowledge = Knowledge("docs", None, None, first, 5)
    assert knowledge.content_db is knowledge.contents_db is first
    assert knowledge.max_results == 5
    assert Knowledge(content_db=first, contents_db=first).contents_db is first
    with pytest.raises(ValueError):
        Knowledge(content_db=first, contents_db=second)
    with pytest.raises(ValueError):
        Knowledge(content_db=first, contents_db=None)
    assert dataclasses.replace(knowledge, contents_db=second).content_db is second
    assert copy.copy(knowledge).content_db is first
    assert Knowledge(**{f.name: getattr(knowledge, f.name) for f in dataclasses.fields(knowledge)}).content_db is first
    knowledge.content_db = second
    assert knowledge.contents_db is second
    knowledge.contents_db = first
    assert knowledge.content_db is first


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
