import asyncio
import copy
import dataclasses
import inspect
import threading

import pytest

from agno.db.sqlite import SqliteDb
from agno.fs.errors import InvalidPathError
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page._source import page_path
from agno.utils.bounded import BoundedWorkers


def test_page_public_imports_preserve_types_without_loading_storage():
    import subprocess
    import sys
    from pathlib import Path
    from textwrap import dedent

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""
                import json
                import pickle
                import sys

                class BlockStorageImports:
                    def find_spec(self, fullname, path=None, target=None):
                        blocked = (
                            "sqlalchemy", "psycopg", "pgvector", "agno.vectordb", "regex",
                            "agno.knowledge.page._coordinator", "agno.knowledge.page._source",
                        )
                        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
                            raise AssertionError("Page types eagerly imported " + fullname)

                sys.meta_path.insert(0, BlockStorageImports())
                from agno.knowledge import page
                from agno.knowledge.page import types

                expected = {
                    "GrepMatch", "GrepResult", "Page", "PageChanged", "PageError", "PageList",
                    "PageNotFound", "PageRead", "PageResult", "PageSearchConfig", "PageSourceBinding",
                    "PageSourceBusy", "PageSourceMigration", "SearchHit", "SearchResult",
                    "SearchUnavailable", "SyncFailed", "SyncReport", "encoded_size", "tool_error",
                }
                assert expected | {"PageFileSystem"} <= set(page.__all__)
                for name in expected:
                    assert getattr(page, name) is getattr(types, name)
                assert page.SearchResult().model_dump() == {
                    "schema_version": 1, "results": (), "partial": False, "truncated": False,
                    "omitted_count": 0, "warnings": (),
                }
                # The relocation results are frozen, closed models; the busy error is a page error.
                binding = page.PageSourceBinding(
                    namespace="n", filesystem="f", catalog="c", vectors="v", source=None, revision=0
                )
                try:
                    binding.source = "x"
                except Exception as exc:
                    assert type(exc).__name__ == "ValidationError", type(exc)
                else:
                    raise AssertionError("PageSourceBinding is not frozen")
                migration = page.PageSourceMigration(
                    before=binding, after=binding, target_source="https://x/llms.txt", dry_run=True, changed=False
                )
                assert page.PageSourceMigration.model_validate_json(migration.model_dump_json()) == migration
                assert isinstance(page.PageSourceBusy(), page.PageError)
                assert json.loads(page.tool_error(page.PageSourceBusy())) == {"schema_version": 1, "error": "page_source_busy"}
                assert pickle.loads(b"cagno.knowledge.page\\nSearchResult\\n.") is types.SearchResult
                # The transform is a pure source callable; it loads no storage either.
                assert page.DocumentationMarkdown(profile="markdown")("x", path="/x.md") == "x"
                assert page.normalize_mdx("<Note>hi</Note>\\n") == "**Note:** hi\\n"
                assert "agno.knowledge.knowledge" not in sys.modules
            """),
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_relocation_cli_guidance_follows_the_migration_result():
    import importlib.util
    from pathlib import Path

    from agno.knowledge.page import PageSourceBinding, PageSourceMigration

    path = Path(__file__).resolve().parents[5] / "cookbook/05_agent_os/27_public_pages/migrate_page_source.py"
    spec = importlib.util.spec_from_file_location("migrate_page_source", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)  # argparse and json only; the demo import happens inside main()

    old, new = "https://docs.example.com/llms.txt", "https://public.example.com/llms.txt"
    at_old = PageSourceBinding(namespace="n", filesystem="f", catalog="c", vectors="v", source=old, revision=2)
    at_new = at_old.model_copy(update={"source": new, "revision": 3})

    dry = cli.next_steps(
        PageSourceMigration(before=at_old, after=at_old, target_source=new, dry_run=True, changed=False)
    )
    assert dry.startswith("Dry run: no source relocation was applied") and "--apply" in dry
    assert "Relocation applied" not in dry and "already points" not in dry

    dry_current = cli.next_steps(
        PageSourceMigration(before=at_new, after=at_new, target_source=new, dry_run=True, changed=False)
    )
    assert (
        dry_current.startswith("Dry run: no source relocation was applied")
        and "already points to the target" in dry_current
    )
    assert "--apply" not in dry_current

    applied = cli.next_steps(
        PageSourceMigration(before=at_old, after=at_new, target_source=new, dry_run=False, changed=True)
    )
    assert applied.startswith("Relocation applied") and "PAGE_DEMO_INDEX_URL" in applied and "restart" in applied
    assert "index_version" in applied

    noop = cli.next_steps(
        PageSourceMigration(before=at_new, after=at_new, target_source=new, dry_run=False, changed=False)
    )
    assert noop.startswith("The binding already points to the target; no additional binding change was made")
    assert "Relocation applied" not in noop and "Dry run" not in noop and "index_version" in noop


def test_constructor_is_keyword_only_and_preserves_dataclass_database_field():
    first, second = SqliteDb(), SqliteDb()
    knowledge = Knowledge(name="docs", content_db=first, max_results=5)
    assert knowledge.contents_db is first and knowledge.max_results == 5
    assert dataclasses.replace(knowledge, contents_db=second).content_db is second
    assert copy.copy(knowledge).contents_db is first
    assert Knowledge(**{f.name: getattr(knowledge, f.name) for f in dataclasses.fields(knowledge)}).contents_db is first
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in inspect.signature(Knowledge).parameters.values())
    with pytest.raises(TypeError):
        Knowledge("docs")
    with pytest.raises(ValueError, match="same database object"):
        dataclasses.replace(knowledge, content_db=second)
    fields = {f.name for f in dataclasses.fields(knowledge)}
    assert "contents_db" in fields and "content_db" not in fields


def test_database_constructor_aliases_and_assignment_share_one_value():
    first, second = SqliteDb(), SqliteDb()
    for kwargs in ({"content_db": first}, {"contents_db": first}, {"content_db": first, "contents_db": first}):
        knowledge = Knowledge(**kwargs)
        assert knowledge.content_db is knowledge.contents_db is first
        knowledge.content_db = second
        assert knowledge.contents_db is second
        knowledge.contents_db = first
        assert knowledge.content_db is first
        knowledge.content_db = None
        assert knowledge.contents_db is None
        assert set(vars(knowledge)).intersection({"content_db", "contents_db"}) == {"contents_db"}
    for kwargs in ({}, {"content_db": None}, {"contents_db": None}, {"content_db": None, "contents_db": None}):
        assert Knowledge(**kwargs).content_db is None
    for kwargs in (
        {"content_db": first, "contents_db": second},
        {"content_db": None, "contents_db": first},
        {"content_db": first, "contents_db": None},
    ):
        with pytest.raises(ValueError, match="same database object"):
            Knowledge(**kwargs)


def test_dataclass_serialization_and_copy_keep_the_legacy_spelling():
    knowledge = Knowledge(name="docs", description="Reference", max_results=4, max_embedding_retries=2)
    serialized = dataclasses.asdict(knowledge)
    assert "contents_db" in serialized and "content_db" not in serialized
    restored = Knowledge(**serialized)
    assert restored.name == "docs" and restored.max_results == 4 and restored.max_embedding_retries == 2
    assert dataclasses.asdict(restored) == serialized
    assert dataclasses.asdict(copy.deepcopy(knowledge)) == serialized


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
    from agno.knowledge.page._source import PageSource
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
    from agno.knowledge.page._source import PageSource
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
