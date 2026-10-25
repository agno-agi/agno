"""Work lifecycle parity on PostgreSQL and SQLite, sync and native async."""

import inspect
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agno.agent import Agent
from agno.company import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.registry import Registry
from agno.team import Team


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def db(request, tmp_path):
    backend = request.param
    suffix = uuid4().hex[:12]
    kwargs = {
        "products_table": "products_" + suffix,
        "projects_table": "projects_" + suffix,
        "tasks_table": "tasks_" + suffix,
    }
    if "postgres" in backend:
        kwargs.update(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema="products_" + suffix)
        cls = AsyncPostgresDb if backend.startswith("async") else PostgresDb
    else:
        kwargs.update(db_file=str(tmp_path / "products.db"))
        cls = AsyncSqliteDb if backend.startswith("async") else SqliteDb
    database = cls(**kwargs)
    try:
        yield database
    finally:
        if "postgres" in backend:
            # Only this fixture's randomly named schema is removed.
            if isinstance(database, AsyncBaseDb):
                async with database.db_engine.begin() as conn:
                    await conn.execute(text('DROP SCHEMA IF EXISTS "' + database.db_schema + '" CASCADE'))
            else:
                with database.db_engine.begin() as conn:
                    conn.execute(text('DROP SCHEMA IF EXISTS "' + database.db_schema + '" CASCADE'))
        await call(database.close)


async def call(fn, /, *args, **kwargs):
    result = fn(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def manager(db):
    registry = Registry(
        agents=[Agent(id="writer"), Agent(id="current"), Agent(id="stale")], teams=[Team(id="writers", members=[])]
    )
    return AsyncCompanyManager(db, registry) if isinstance(db, AsyncBaseDb) else CompanyManager(db, registry)


@pytest.mark.asyncio
async def test_lifecycle_and_owner_guards(db):
    m = manager(db)
    assert await call(m.list_tasks) == ([], 0)
    parent = await call(m.create, name="SDK", user_id="alice")
    project = await call(m.create_project, product_id=parent["id"], name="Release", user_id="alice")
    record = await call(
        m.create_task,
        product_id=parent["id"],
        title="Ship",
        user_id="alice",
        scoped_user_id="alice",
        project_id=project["id"],
    )
    rid = record["id"]
    assert record["status"] == "backlog"
    assert await call(m.get_task, rid, user_id="bob") is None
    assert await call(m.update_task, rid, user_id="bob", brief="No") is None
    assert await call(m.delete_task, rid, user_id="bob") is False
    assert await call(m.transition_task, task_id=rid, target="cancelled", reason="Stop", user_id="bob") is None
    changed = await call(m.update_task, rid, brief="Changed")
    assert changed["brief"] == "Changed"
    assert changed["updated_at"] >= record["created_at"]
    with pytest.raises(ValueError):
        await call(m.transition_task, task_id=rid, target="done", reason="Skip")
    with pytest.raises(ValueError):
        await call(m.transition_task, task_id=rid, target="cancelled", reason=" ")
    states = ["ready", "in_progress", "in_review", "done"]
    for state in states:
        kwargs = {"executor_type": "agent", "executor_id": "writer"} if state == "ready" else {}
        result = await call(
            m.transition_task, task_id=rid, target=state, reason="Reviewed", accepted_by="reviewer", **kwargs
        )
        assert result["status"] == state
    assert [entry["target"] for entry in result["transitions"]] == states
    assert all(entry["user_id"] == "reviewer" for entry in result["transitions"])
    with pytest.raises(ValueError):
        await call(m.transition_task, task_id=rid, target="cancelled", reason="Terminal")
    assert await call(m.restore_task, rid) is None
    assert await call(m.delete_task, rid)
    assert await call(m.get_task, rid) is None
    assert await call(m.update_task, rid, brief="Deleted") is None
    assert await call(m.get_task, rid, include_deleted=True)
    assert (await call(m.list_tasks))[1] == 0
    assert (await call(m.list_tasks, include_deleted=True))[1] == 1
    assert await call(m.restore_task, rid, user_id="bob") is None
    assert (await call(m.restore_task, rid))["status"] == "done"
    assert await call(m.get_task, "missing") is None
    assert await call(m.transition_task, task_id="missing", target="cancelled", reason="Missing") is None


@pytest.mark.asyncio
async def test_filters_and_stable_paging(db):
    m = manager(db)
    parents = [await call(m.create, name="A"), await call(m.create, name="B")]
    now = int(time.time())
    for i, owner in enumerate(["alice", "bob", "alice", None, "alice", "bob"]):
        await call(
            db.create_task,
            {
                "id": str(i),
                "product_id": parents[i % 2]["id"],
                "title": "Same",
                "status": "backlog",
                "user_id": owner,
                "created_at": now,
                "transitions": [],
            },
        )
    await call(m.transition_task, task_id="0", target="cancelled", reason="Stop")
    pages = [await call(m.list_tasks, user_id="alice", status="backlog", limit=1, page=p) for p in [1, 2]]
    assert [p[1] for p in pages] == [2, 2]
    assert [p[0][0]["id"] for p in pages] == ["4", "2"]
    assert (await call(m.list_tasks, product_id=parents[1]["id"]))[1] == 3
    assert (await call(m.list_tasks, status="cancelled"))[1] == 1
    assert (await call(m.list_tasks, user_id="absent")) == ([], 0)


@pytest.mark.asyncio
async def test_validation_parent_visibility_and_immutable_fields(db):
    m = manager(db)
    parent = await call(m.create, name="SDK", user_id="alice")
    project = await call(m.create_project, product_id=parent["id"], name="Release", user_id="alice")
    with pytest.raises(LookupError):
        await call(
            m.create_task,
            product_id=parent["id"],
            title="Hidden",
            user_id="bob",
            scoped_user_id="bob",
            project_id=project["id"],
        )
    project = await call(m.create_project, product_id=parent["id"], name="Release", user_id="alice")
    record = await call(m.create_task, product_id=parent["id"], title="Work", project_id=project["id"])
    for fields in [
        {"status": "done"},
        {"id": "other"},
        {"product_id": "other"},
        {"created_at": 0},
        {"deleted_at": 1},
        {"title": None},
        {"brief": []},
    ]:
        with pytest.raises(ValueError):
            await call(m.update_task, record["id"], **fields)
        with pytest.raises(ValueError):
            await call(db.update_task, record["id"], **fields)
    for kwargs in [{"limit": 0}, {"page": 0}]:
        with pytest.raises(ValueError):
            await call(m.list_tasks, **kwargs)
        with pytest.raises(ValueError):
            await call(db.get_tasks, **kwargs)


@pytest.mark.asyncio
async def test_custom_table_migrations_and_configuration_roundtrip(db):
    m = manager(db)
    parent = await call(m.create, name="SDK")
    project = await call(m.create_project, product_id=parent["id"], name="Release", user_id="alice")
    record = await call(
        m.create_task, product_id=parent["id"], title="Roundtrip", user_id="alice", project_id=project["id"]
    )
    assert await call(db.table_exists, db.tasks_table_name)
    assert not await call(db.table_exists, "agno_company_tasks")
    assert await call(db.get_latest_schema_version, db.tasks_table_name)
    data = db.to_dict()
    assert data["tasks_table"] == db.tasks_table_name
    reopened = type(db).from_dict(data)
    try:
        assert reopened.tasks_table_name == db.tasks_table_name
        assert await call(reopened.get_task, record["id"], user_id="alice") == record
    finally:
        await call(reopened.close)


@pytest.mark.asyncio
async def test_task_acceptance_and_project_consistency(db):
    m = manager(db)
    a = await call(m.create, name="A")
    b = await call(m.create, name="B")
    project = await call(m.create_project, product_id=b["id"], name="Other")
    with pytest.raises(ValueError):
        await call(m.create_task, product_id=a["id"], title="Wrong", project_id=project["id"])
    own_project = await call(m.create_project, product_id=a["id"], name="Release")
    task = await call(m.create_task, product_id=a["id"], title="Work", project_id=own_project["id"])
    with pytest.raises(ValueError):
        await call(m.update_task, task["id"], project_id=project["id"])
    ready = await call(
        m.transition_task,
        task_id=task["id"],
        target="ready",
        reason="Accepted",
        accepted_by="alice",
        executor_type="team",
        executor_id="writers",
    )
    assert ready["accepted_by"] == "alice"
    assert ready["accepted_at"] >= task["created_at"]
    with pytest.raises(ValueError, match="Backlog"):
        await call(m.update_task, task["id"], brief="Changed")
    assert await call(db.update_task, task["id"], brief="Bypass") is None
    backlog = await call(m.transition_task, task_id=task["id"], target="backlog", reason="Rescope", accepted_by="alice")
    assert all(backlog[k] is None for k in ["executor_id", "executor_type", "accepted_at", "accepted_by"])
    assert (await call(m.update_task, task["id"], brief="Changed"))["brief"] == "Changed"


@pytest.mark.asyncio
async def test_stale_acceptance_cannot_overwrite_a_backlog_roundtrip(db, monkeypatch):
    import agno.db.schemas.tasks as task_schema

    m = manager(db)
    parent = await call(m.create, name="SDK")
    project = await call(m.create_project, product_id=parent["id"], name="Release")
    task = await call(m.create_task, product_id=parent["id"], title="Work", project_id=project["id"])
    # Capture the observed row at the SQL validation boundary. The later writer
    # sees Backlog again, but must not overwrite the intervening history.
    original = task_schema.task_transition_fields
    if isinstance(db, AsyncBaseDb):
        # Native async concurrency is covered by the same SQL predicate. Use
        # two async transactions below instead of reentering the event loop.
        import asyncio

        observed = asyncio.Event()
        resume = asyncio.Event()
        first = True
        original_execute = db.async_session_factory.class_.execute

        async def execute(session, statement, *args, **kwargs):
            nonlocal first
            # Pause the transition transaction, not preliminary manager validation.
            in_transition = session.in_transaction()
            result = await original_execute(session, statement, *args, **kwargs)
            if (
                first
                and in_transition
                and statement.is_select
                and getattr(statement, "selected_columns", None) is not None
                and "executor_type" in statement.selected_columns
            ):
                first = False
                observed.set()
                await resume.wait()
            return result

        monkeypatch.setattr(db.async_session_factory.class_, "execute", execute)
        pending = asyncio.create_task(
            m.transition_task(
                task_id=task["id"], target="ready", reason="Stale", executor_type="agent", executor_id="stale"
            )
        )
        await asyncio.wait_for(observed.wait(), timeout=5)
        await m.transition_task(
            task_id=task["id"], target="ready", reason="Current", executor_type="agent", executor_id="current"
        )
        await m.transition_task(task_id=task["id"], target="backlog", reason="Rescope")
        resume.set()
        assert await asyncio.wait_for(pending, timeout=5) is None
    else:
        first = True

        def intervening(existing, *args, **kwargs):
            nonlocal first
            if first:
                first = False
                from concurrent.futures import ThreadPoolExecutor

                # Sync adapters use thread-scoped Sessions; the competing writer
                # needs its own thread to represent a separate transaction.
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(
                        m.transition_task,
                        task_id=task["id"],
                        target="ready",
                        reason="Current",
                        executor_type="agent",
                        executor_id="current",
                    ).result(timeout=5)
                    pool.submit(m.transition_task, task_id=task["id"], target="backlog", reason="Rescope").result(
                        timeout=5
                    )
            return original(existing, *args, **kwargs)

        monkeypatch.setattr(task_schema, "task_transition_fields", intervening)
        assert (
            m.transition_task(
                task_id=task["id"], target="ready", reason="Stale", executor_type="agent", executor_id="stale"
            )
            is None
        )
    saved = await call(m.get_task, task["id"])
    assert saved["status"] == "backlog" and saved["executor_id"] is None
    assert [entry["reason"] for entry in saved["transitions"]] == ["Current", "Rescope"]


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["projects", "tasks"])
@pytest.mark.parametrize("isolation", [False, True])
async def test_http_collaborative_work_and_shared_deletion(db, resource, isolation):
    import jwt
    from httpx import ASGITransport, AsyncClient

    from agno.os import AgentOS, CompanyConfig
    from agno.os.config import AuthorizationConfig

    secret = "company-shared-work-tests"
    os_id = "company-shared-work"

    def headers(user):
        token = jwt.encode(
            {
                "sub": user,
                "aud": os_id,
                "scopes": [resource + ":read", resource + ":write", resource + ":delete", "agents:writer:run"],
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            },
            secret,
            algorithm="HS256",
        )
        return {"Authorization": "Bearer " + token}

    m = manager(db)
    product = await call(m.create, name="Shared", user_id="alice")
    project = await call(m.create_project, product_id=product["id"], name="Shared project", user_id="alice")
    app = AgentOS(
        agents=[Agent(id="writer")],
        id=os_id,
        db=db,
        company=CompanyConfig(),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[secret], algorithm="HS256", user_isolation=isolation
        ),
    ).get_app()
    field = "title" if resource == "tasks" else "name"
    initial_status = "backlog" if resource == "tasks" else "proposed"
    root = "/company/" + resource
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = {"product_id": product["id"], field: "Work"}
        if resource == "tasks":
            body["project_id"] = project["id"]
        # A writer may propose its own work under another owner's shared parent.
        response = await client.post(root, json=body, headers=headers("bob"))
        assert response.status_code == 201, response.text
        own = response.json()
        assert own["user_id"] == "bob" and own["status"] == initial_status
        other = (
            project
            if resource == "projects"
            else await call(
                m.create_task, product_id=product["id"], title="Alice task", user_id="alice", project_id=project["id"]
            )
        )
        path = root + "/" + other["id"]
        assert (await client.get(path, headers=headers("bob"))).status_code == 200
        pages = [
            (
                await client.get(
                    root, params={"status": initial_status, "limit": 1, "page": page}, headers=headers("bob")
                )
            ).json()
            for page in (1, 2)
        ]
        assert all(page["meta"]["total_count"] == 2 for page in pages)
        assert {page["data"][0]["id"] for page in pages} == {own["id"], other["id"]}
        assert (await client.patch(path, json={field: "Renamed"}, headers=headers("bob"))).status_code == 200
        if resource == "tasks":
            # Collaborators can assign another creator's Task to a shared Project.
            own_path = path
            assert (await client.patch(own_path, json={"project_id": None}, headers=headers("bob"))).status_code == 422
            assert (
                await client.patch(own_path, json={"project_id": project["id"]}, headers=headers("bob"))
            ).status_code == 200
            target = {"target": "ready", "executor_type": "agent", "executor_id": "writer", "reason": "Accept"}
        else:
            target = {"target": "active", "reason": "Accept"}
        accepted = await client.post(path + "/transitions", json=target, headers=headers("bob"))
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["user_id"] == "alice"
        assert accepted.json()["transitions"][-1]["user_id"] == "bob"
        if resource == "tasks":
            assert accepted.json()["accepted_by"] == "bob"
            assert (await client.patch(path, json={field: "Frozen"}, headers=headers("bob"))).status_code == 409
            returned = await client.post(
                path + "/transitions", json={"target": "backlog", "reason": "Clarify scope"}, headers=headers("bob")
            )
            assert returned.status_code == 200
            assert returned.json()["accepted_by"] is None
            assert (await client.patch(path, json={field: "Rescoped"}, headers=headers("bob"))).status_code == 200
        cancelled = await client.post(
            path + "/transitions", json={"target": "cancelled", "reason": "Stop"}, headers=headers("bob")
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["transitions"][-1]["user_id"] == "bob"
        assert (await client.delete(path, headers=headers("alice"))).status_code == 204
        assert (await client.get(path, headers=headers("bob"))).status_code == 404
        assert (await client.get(path, params={"include_deleted": True}, headers=headers("bob"))).status_code == 200
        # Archive and restore need only the delete scope; the creator stays recorded.
        restored = await client.post(path + "/restore", headers=headers("bob"))
        assert restored.status_code == 200, restored.text
        assert restored.json()["user_id"] == "alice"
        assert (await client.patch(root + "/missing", json={field: "No"}, headers=headers("bob"))).status_code == 404
