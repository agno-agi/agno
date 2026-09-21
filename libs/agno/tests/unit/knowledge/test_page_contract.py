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
                    "PageSourceBusy", "PageSourceMigration", "PageSyncProgress", "SearchHit", "SearchResult",
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


def _load_public_pages_cookbook(name, monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path

    folder = Path(__file__).resolve().parents[5] / "cookbook/05_agent_os/27_public_pages"
    # Nothing connects at import: the database URL is never dialled and no provider key is read.
    monkeypatch.setenv("PAGE_DEMO_DB_URL", "postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.syspath_prepend(str(folder))
    spec = importlib.util.spec_from_file_location(name, folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_sync_docs_step_streams_page_progress_before_its_report(monkeypatch):
    from agno.knowledge.page import PageSyncProgress, SyncReport
    from agno.run.workflow import StepProgressEvent, WorkflowCompletedEvent
    from agno.workflow import Workflow

    demo = _load_public_pages_cookbook("public_pages", monkeypatch)
    snapshots = [
        PageSyncProgress(stage="waiting"),
        PageSyncProgress(stage="discovered", discovered=2),
        PageSyncProgress(stage="publishing", discovered=2, processed=1, updated=1, path="/a.md"),
        PageSyncProgress(stage="publishing", discovered=2, processed=2, updated=1, failed=1, path="/b.md"),
        PageSyncProgress(stage="pruning", discovered=2, processed=2, updated=1, failed=1, deleted=3, path="/old.md"),
    ]
    report = SyncReport(status="partial", discovered=2, updated=1, deleted=3, failed=1, errors=("page_sync_failed",))
    requested = []

    async def stream(**kwargs):
        requested.append(kwargs)
        for snapshot in snapshots:
            yield snapshot
        yield report

    async def finished(**kwargs):
        return report

    monkeypatch.setattr(demo.knowledge, "astream_sync_pages", stream, raising=False)
    monkeypatch.setattr(demo.knowledge, "async_sync_pages", finished)
    # The cookbook's own step, in a workflow without the demo database.
    workflow = Workflow(id="sync-docs", input_schema=demo.SyncRequest, steps=demo.sync.steps, telemetry=False)

    events = [event async for event in workflow.arun(input={"reindex": True}, stream=True, stream_events=True)]

    progress = [event for event in events if isinstance(event, StepProgressEvent)]
    assert [event.content for event in progress] == [
        "Waiting to synchronize pages",
        "Discovered 2 pages",
        "Processed 1 of 2 pages (1 updated, 0 failed)",
        "Processed 2 of 2 pages (1 updated, 1 failed)",
        "Pruned 3 stale pages",
    ]
    assert [event.data for event in progress] == [snapshot.model_dump() for snapshot in snapshots]
    completed = events[-1]
    assert isinstance(completed, WorkflowCompletedEvent) and completed.content == report.model_dump()
    assert [result.success for result in completed.step_results] == [False]
    assert requested == [{"url": demo.index_url, "reindex": True}]

    # A request the schema rejects never reaches the page source.
    with pytest.raises(ValueError):
        [event async for event in workflow.arun(input={"reindex": "sometimes"}, stream=True, stream_events=True)]
    assert len(requested) == 1


@pytest.mark.asyncio
async def test_sync_docs_streams_page_progress_without_storing_it(monkeypatch):
    from agno.db.in_memory import InMemoryDb
    from agno.knowledge.page import PageSyncProgress, SyncReport
    from agno.run.workflow import StepProgressEvent

    demo = _load_public_pages_cookbook("public_pages", monkeypatch)
    pages = 3

    async def stream(**kwargs):
        yield PageSyncProgress(stage="discovered", discovered=pages)
        for processed in range(1, pages + 1):
            yield PageSyncProgress(stage="publishing", discovered=pages, processed=processed)
        yield SyncReport(status="unchanged", discovered=pages)

    monkeypatch.setattr(demo.knowledge, "astream_sync_pages", stream)
    # The cookbook's own workflow as AgentOS serves it, which stores run events, without the demo database.
    monkeypatch.setattr(demo.sync, "db", InMemoryDb())
    monkeypatch.setattr(demo.sync, "telemetry", False)

    for _ in range(2):
        events = [event async for event in demo.sync.arun(input={}, session_id="s", stream=True, stream_events=True)]
        assert len([event for event in events if isinstance(event, StepProgressEvent)]) == pages + 1
        saved = await demo.sync.aget_run_output(run_id=events[-1].run_id, session_id="s")
        stored = [event.event for event in saved.events]
        # One event per page would grow the saved run with the size of the page source.
        assert "StepProgress" not in stored
        assert "StepCompleted" in stored and "WorkflowCompleted" in stored


def test_public_pages_serves_one_loopback_agentos():
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[5] / "cookbook/05_agent_os/27_public_pages/public_pages.py"
    serves = [
        {keyword.arg: ast.literal_eval(keyword.value) for keyword in node.keywords if keyword.arg in ("host", "port")}
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "serve"
    ]
    assert serves == [{"host": "127.0.0.1", "port": 7777}]


_SYNC_TOKEN = "page-demo-test-token"


def _sync_stream(*events):
    import json

    started = {"event": "StepStarted", "run_id": "run-1", "step_name": "reconcile", "created_at": 1}
    return ["data: " + json.dumps(event) for event in (started, *events)]


def _progress(content):
    return {"event": "StepProgress", "run_id": "run-1", "step_name": "reconcile", "content": content, "created_at": 1}


def _completed(status="completed"):
    report = {"schema_version": 1, "status": status, "discovered": 1, "updated": 1, "failed": 0}
    return {"event": "WorkflowCompleted", "run_id": "run-1", "content": report, "created_at": 1}


async def _run_progress_client(monkeypatch, capsys, lines, argv=(), token=_SYNC_TOKEN):
    import sys

    from agno.client import AgentOSClient

    cli = _load_public_pages_cookbook("page_sync_progress", monkeypatch)
    requests = []

    async def stream(self, endpoint, data, headers=None):
        requests.append((self.base_url, endpoint, data, headers))
        for line in lines:
            yield line

    # The real client and its event parsing run; only the socket is replaced.
    monkeypatch.setattr(AgentOSClient, "_astream_post_form_data", stream)
    monkeypatch.setenv("PAGE_DEMO_SERVER_URL", "http://docs.example.test:7777")
    if token is None:
        monkeypatch.delenv("PAGE_DEMO_SYNC_TOKEN", raising=False)
    else:
        monkeypatch.setenv("PAGE_DEMO_SYNC_TOKEN", token)
    monkeypatch.setattr(sys, "argv", ["page_sync_progress.py", *argv])
    try:
        code = await cli.main()
    except SystemExit as stopped:
        code = stopped.code
    return code, capsys.readouterr(), requests


@pytest.mark.asyncio
@pytest.mark.parametrize("argv,reindex", [((), False), (("--reindex",), True)])
async def test_sync_progress_client_prints_progress_then_the_report(monkeypatch, capsys, argv, reindex):
    import json

    lines = _sync_stream(
        _progress("Discovered 1 pages"), _progress("Processed 1 of 1 pages (1 updated, 0 failed)"), _completed()
    )

    code, output, requests = await _run_progress_client(monkeypatch, capsys, lines, argv)

    assert code == 0
    printed = output.out
    assert printed.index("Discovered 1 pages") < printed.index("Processed 1 of 1 pages (1 updated, 0 failed)")
    assert printed.index("Processed 1 of 1 pages") < printed.index('"status": "completed"')
    assert _SYNC_TOKEN not in printed + output.err
    [(base_url, endpoint, data, headers)] = requests
    assert (base_url, endpoint) == ("http://docs.example.test:7777", "/workflows/sync-docs/runs")
    assert headers == {"Authorization": "Bearer " + _SYNC_TOKEN}
    # The page source stays server-owned: the client sends the typed request and nothing else.
    assert set(data) == {"message", "stream"} and set(json.loads(data["message"])) == {"reason", "reindex"}
    assert json.loads(data["message"])["reindex"] is reindex


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "events",
    [
        pytest.param([_progress("Discovered 1 pages"), {"event": "WorkflowError", "error": "boom"}], id="error"),
        pytest.param([_progress("Discovered 1 pages"), {"event": "WorkflowCancelled", "reason": "stop"}], id="cancel"),
        pytest.param([_completed()], id="no-progress"),
        pytest.param([_progress("Discovered 1 pages"), _completed("partial")], id="partial"),
        pytest.param([_progress("Discovered 1 pages")], id="no-completion"),
    ],
)
async def test_sync_progress_client_fails_when_the_sync_did_not_succeed(monkeypatch, capsys, events):
    code, output, requests = await _run_progress_client(monkeypatch, capsys, _sync_stream(*events))

    assert code != 0 and len(requests) == 1
    assert _SYNC_TOKEN not in output.out + output.err


@pytest.mark.asyncio
async def test_sync_progress_client_needs_the_sync_token_before_it_calls_the_server(monkeypatch, capsys):
    code, output, requests = await _run_progress_client(monkeypatch, capsys, [], token=None)

    assert code != 0 and requests == []
    assert "PAGE_DEMO_SYNC_TOKEN" in output.err


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
