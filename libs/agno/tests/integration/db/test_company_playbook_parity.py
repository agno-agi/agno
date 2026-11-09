"""Company playbook on real SQLite/PostgreSQL, sync and async."""

import asyncio
import inspect
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agno.company import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.fs import FileSystem
from agno.fs.errors import VersionConflictError


async def call(fn, /, *args, **kwargs):
    result = fn(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def db(request, tmp_path):
    suffix = uuid4().hex
    if "postgres" in request.param:
        cls = AsyncPostgresDb if request.param.startswith("async") else PostgresDb
        db = cls(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema="playbook_" + suffix)
    else:
        cls = AsyncSqliteDb if request.param.startswith("async") else SqliteDb
        db = cls(db_file=str(tmp_path / "playbook.db"))
    yield db
    if "postgres" in request.param:
        statement = text('DROP SCHEMA IF EXISTS "' + db.db_schema + '" CASCADE')
        if isinstance(db, AsyncBaseDb):
            async with db.db_engine.begin() as conn:
                await conn.execute(statement)
        else:
            with db.db_engine.begin() as conn:
                conn.execute(statement)
    await call(db.close)


@pytest.mark.asyncio
async def test_playbook_persistence_scope_and_decisions(db):
    cls = AsyncCompanyManager if isinstance(db, AsyncBaseDb) else CompanyManager
    m = cls(db)
    product = await call(m.create, name="SDK", purpose="Build well", user_id="alice")
    pid = product["id"]
    provider = await call(m.get_wiki, pid)
    from agno.context.wiki.provider import WikiContextProvider

    assert isinstance(provider, WikiContextProvider)
    assert (await call(m.list_wiki, pid))[1] == 2
    original = await call(m.read_wiki, pid, "status.md")
    # Wiki pages are shared, so a member who did not create the Product may write them.
    await call(
        m.write_wiki,
        product_id=pid,
        path="status.md",
        content="reviewed",
        expected_version=original.metadata.version,
        user_id="bob",
    )
    with pytest.raises(VersionConflictError):
        await call(
            m.write_wiki,
            product_id=pid,
            path="status.md",
            content="stale",
            expected_version=original.metadata.version,
            user_id="alice",
        )
    fresh = cls(db)
    assert (await call(fresh.read_wiki, pid, "status.md")).content == "reviewed"
    entry = await call(
        m.log_decision,
        decision="Ship",
        reasoning="tests passed",
        context="review",
        outcome="approved",
        user_id="alice",
        session_id="s",
        agent_id="a",
    )
    rows, total = await call(fresh.list_decisions, agent_id="a", session_id="s", days=1)
    assert total == 1 and rows[0].id == entry.id and rows[0].user_id == "alice"
    assert len(await call(db.get_learnings, learning_type="decision_log", namespace="company")) == 1
    assert "decisions.md" not in [page.path for page in (await call(m.list_wiki, pid))[0]]


@pytest.mark.asyncio
async def test_filesystem_async_parity_and_atomic_creation(db):
    fs = FileSystem(db, namespace="company-tests/" + uuid4().hex)
    assert (await fs.awrite("status.md", "first", expected_version=0)).version == 1
    with pytest.raises(VersionConflictError):
        await fs.awrite("status.md", "lost", expected_version=0)
    assert (await fs.awrite("status.md", "second", expected_version=1)).version == 2
    await fs.aappend("status.md", "third")
    await fs.areplace_lines("status.md", 1, 1, "updated")
    assert (await fs.aread("status.md")).startswith("updated")
    assert (await fs.asearch("third"))[0].path == "status.md"
    assert (await fs.acontains(["third"])).found == ["third"]
    await fs.amove("status.md", "moved.md")
    assert (await fs.ausage()).file_count == 1
    assert await fs.adelete("moved.md")
    assert await fs.alist() == []


@pytest.mark.asyncio
async def test_two_writers_cannot_overwrite_one_version(db):
    namespace = "company-tests/" + uuid4().hex
    left, right = FileSystem(db, namespace=namespace), FileSystem(db, namespace=namespace)
    await left.awrite("status.md", "original", expected_version=0)
    results = await asyncio.gather(
        left.awrite("status.md", "left", expected_version=1),
        right.awrite("status.md", "right", expected_version=1),
        return_exceptions=True,
    )
    assert sum(isinstance(result, VersionConflictError) for result in results) == 1
    assert (await left.aread_with_meta("status.md")).metadata.version == 2


@pytest.mark.asyncio
async def test_proposal_edit_rechecks_status_in_storage(db):
    m = AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db)
    product = await call(m.create, name="SDK", user_id="alice")
    project = await call(m.create_project, product_id=product["id"], name="Release", user_id="alice")
    await call(m.transition_project, project_id=project["id"], target="active", reason="accepted", user_id="alice")
    assert (
        await call(m.update_project, project["id"], name="stale proposal", user_id="alice", expected_status="proposed")
        is None
    )
    assert (await call(m.get_project, project["id"]))["name"] == "Release"


@pytest.mark.asyncio
async def test_async_filesystem_serialization_and_user_partitions(db):
    source = FileSystem(db, namespace="company-tests/" + uuid4().hex, user_scoped=True)
    restored = FileSystem.from_dict(source.to_dict(), db=db)
    alice, bob = restored.resolve(user_id="alice"), restored.resolve(user_id="bob")
    await alice.awrite("note.md", "private", expected_version=0)
    assert await bob.aread("note.md") is None
    assert await restored.apartitions() == ["alice"]
    assert await restored.backend.aupgrade_schema() is False


@pytest.mark.asyncio
async def test_decision_write_does_not_claim_success_on_silent_storage_failure(db, monkeypatch):
    m = AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db)
    if isinstance(db, AsyncBaseDb):

        async def fail(**kwargs):
            return None
    else:

        def fail(**kwargs):
            return None

    monkeypatch.setattr(db, "upsert_learning", fail)
    with pytest.raises(RuntimeError, match="not persisted"):
        await call(m.log_decision, decision="must not claim success")


@pytest.mark.asyncio
async def test_cold_filesystem_creation_on_two_backends(db):
    from agno.fs.db import AsyncDbFileSystem, DbFileSystem

    cls = AsyncDbFileSystem if isinstance(db, AsyncBaseDb) else DbFileSystem
    table = "cold_" + uuid4().hex
    options = {"db": db, "table_name": table, "db_schema": getattr(db, "db_schema", None)}
    left, right = FileSystem(cls(**options)), FileSystem(cls(**options))
    await asyncio.gather(
        left.awrite("left.md", "left", expected_version=0), right.awrite("right.md", "right", expected_version=0)
    )
    assert {row.path for row in await left.alist()} == {"left.md", "right.md"}


@pytest.mark.asyncio
async def test_async_memory_filesystem_shares_one_connection_safely():
    db = AsyncSqliteDb(db_url="sqlite+aiosqlite:///:memory:")
    try:
        left, right = FileSystem(db), FileSystem(db)
        await asyncio.gather(left.awrite("left.md", "left"), right.awrite("right.md", "right"))
        assert {row.path for row in await left.alist()} == {"left.md", "right.md"}
        await asyncio.gather(left.aappend("left.md", "more"), right.aappend("right.md", "more"))
        assert "more" in await right.aread("left.md")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_durable_wiki_tools_use_native_async_filesystem(db):
    from agno.context.wiki.backend import DurableWikiBackend
    from agno.context.wiki.provider import WikiContextProvider

    fs = FileSystem(db, namespace="company-tests/" + uuid4().hex, user_scoped=False)
    wiki = WikiContextProvider(id="test-wiki", name="Test wiki", backend=DurableWikiBackend(fs))
    tools = wiki._build_write_tools()
    assert (await tools.awrite_file("status.md", "draft")).startswith("Wrote")
    assert "draft" in await tools.aread_file("status.md")
    assert '"status.md"' in await tools.alist_files()
    assert '"matches_found": 1' in await tools.asearch_content("draft")
    assert '"draft"' in await tools.acheck_lines(["draft"])
    assert (await tools.aappend_file("status.md", "review", unique=True)).startswith("Appended")
    assert (await tools.areplace_lines("status.md", 1, 1, "ready for review")).startswith("Replaced")
    assert (await tools.amove_file("status.md", "renamed.md")).startswith("Moved")
    assert (await tools.adelete_file("renamed.md")).startswith("Deleted")
    assert await fs.alist() == []


@pytest.mark.asyncio
async def test_company_recall_is_shared_and_agent_attribution_is_bound(db):
    import json

    from agno.company.decisions import CompanyDecisionLogStore
    from agno.registry._reserved import COMPANY_MANAGER_ID
    from agno.run import RunContext
    from agno.tools.company import CompanyTools

    m = AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db)
    human = await call(m.log_decision, decision="Human review decision", user_id="alice")
    tools = CompanyTools(db)
    context = RunContext(run_id="r", session_id="s", user_id="bob")
    direct = json.loads(await tools.alog_company_decision("Caller decision", _agno_run_context=context))
    assert direct["agent_id"] is None and direct["user_id"] == "bob"
    store = CompanyDecisionLogStore(db)
    learned_tools = await store.aget_tools(agent_id="other-agent")
    fn = next(tool for tool in learned_tools if tool.name == "log_company_decision")
    own = json.loads(await fn.entrypoint("Other agent decision", _agno_run_context=context))
    assert own["agent_id"] == "other-agent"
    recalled = await store.arecall(agent_id=COMPANY_MANAGER_ID, session_id="new-session")
    assert {entry.id for entry in recalled} == {human.id, direct["id"], own["id"]}
    assert len(await store.asearch(agent_id="other-agent")) == 1
    assert await store.asearch(agent_id=COMPANY_MANAGER_ID) == []
    if not isinstance(db, AsyncBaseDb):
        sync_tool = store.get_tools(agent_id="sync-agent")[0]
        entry = json.loads(sync_tool("Sync agent decision", _agno_run_context=context))
        assert entry["agent_id"] == "sync-agent"
        assert len(store.recall(agent_id=COMPANY_MANAGER_ID)) == 4
        assert len(store.search(agent_id="sync-agent")) == 1
