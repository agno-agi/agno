"""Cascading archive through Company managers and HTTP on all four SQL adapters."""

import inspect
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from agno.agent import Agent
from agno.company import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.registry import Registry


async def call(fn, /, *args, **kwargs):
    result = fn(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def db(request, tmp_path, monkeypatch):
    providers = []
    get_app = AgentOS.get_app

    def tracked_app(agent_os, *args, **kwargs):
        app = get_app(agent_os, *args, **kwargs)
        provider = agent_os._task_execution_provider
        if provider is not None and provider not in providers:
            providers.append(provider)
        return app

    monkeypatch.setattr(AgentOS, "get_app", tracked_app)
    backend = request.param
    suffix = uuid4().hex[:12]
    kwargs = {name + "_table": name + "_" + suffix for name in ("products", "projects", "tasks")}
    if "postgres" in backend:
        kwargs.update(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema="archive_" + suffix)
        cls = AsyncPostgresDb if backend.startswith("async") else PostgresDb
    else:
        kwargs.update(db_file=str(tmp_path / "company.db"))
        cls = AsyncSqliteDb if backend.startswith("async") else SqliteDb
    database = cls(**kwargs)
    try:
        yield database
    finally:
        for provider in providers:
            await provider.aclose()
        if "postgres" in backend:
            statement = text('DROP SCHEMA IF EXISTS "' + database.db_schema + '" CASCADE')
            if isinstance(database, AsyncBaseDb):
                async with database.db_engine.begin() as conn:
                    await conn.execute(statement)
            else:
                with database.db_engine.begin() as conn:
                    conn.execute(statement)
        await call(database.close)


def manager(db):
    registry = Registry(agents=[Agent(id="writer", telemetry=False)])
    return (
        AsyncCompanyManager(db, registry=registry)
        if isinstance(db, AsyncBaseDb)
        else CompanyManager(db, registry=registry)
    )


@pytest.mark.asyncio
async def test_product_cascade_exact_restore_and_repeated_cycles(db, monkeypatch):
    import agno.db.sql.company as archive

    # Provenance must not depend on timestamps: every archive shares one second.
    monkeypatch.setattr(archive.time, "time", lambda: 1800000000)
    m = manager(db)
    product = await call(m.create, name="SDK", user_id="owner")
    project = await call(m.create_project, product_id=product["id"], name="Release", user_id="collaborator")
    project = await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    old_project = await call(m.create_project, product_id=product["id"], name="Old")
    await call(m.transition_project, project_id=old_project["id"], target="active", reason="Approved")
    old_project_task = await call(
        m.create_task, product_id=product["id"], title="Old project task", project_id=old_project["id"]
    )
    await call(m.delete_project, old_project["id"])
    old_task = await call(
        m.create_task, product_id=product["id"], title="Separately archived", project_id=project["id"]
    )
    await call(m.delete_task, old_task["id"])
    tasks = [
        await call(
            m.create_task, product_id=product["id"], title="Release notes", project_id=project["id"], user_id="other"
        ),
        await call(
            db.create_task,
            dict(
                id="legacy-independent",
                product_id=product["id"],
                title="Independent",
                status="backlog",
                created_at=1,
                transitions=[],
            ),
        ),
    ]
    for _ in range(2):
        assert not await call(m.delete, product["id"], user_id="wrong")
        assert await call(m.delete, product["id"], user_id="owner")
        assert not await call(m.delete, product["id"], user_id="owner")
        for get, row in [(m.get_project, project), *[(m.get_task, t) for t in tasks]]:
            saved = await call(get, row["id"], include_deleted=True)
            assert saved["deleted_at"] is not None
            assert saved["status"] == row["status"]
            assert saved["transitions"][-1]["archived_by"] == {"type": "product", "id": product["id"]}
        assert (await call(m.list, include_deleted=True))[1] == 1
        assert (await call(m.list))[1] == 0
        for include_deleted in [False, True]:
            assert await call(m.list_projects, include_deleted=include_deleted) == ([], 0)
            assert await call(m.list_tasks, include_deleted=include_deleted) == ([], 0)
        with pytest.raises(ValueError, match="archived"):
            await call(m.restore_project, project["id"])
        with pytest.raises(ValueError, match="archived"):
            await call(m.restore_task, tasks[0]["id"])
        assert await call(m.restore, product["id"], user_id="wrong") is None
        assert await call(m.restore, product["id"], user_id="owner")
        assert await call(m.restore, product["id"]) is None
        assert await call(m.get_project, project["id"])
        assert all([await call(m.get_task, t["id"]) for t in tasks])
        assert await call(m.get_project, old_project["id"]) is None
        assert await call(m.get_task, old_project_task["id"]) is None
        assert await call(m.get_task, old_task["id"]) is None
    assert await call(m.restore_project, old_project["id"])
    assert await call(m.get_task, old_project_task["id"])
    assert await call(m.get_task, old_task["id"]) is None
    # A new, separate archive must not be revived by an old cascade.
    await call(m.delete_task, tasks[0]["id"])
    await call(m.delete, product["id"])
    await call(m.restore, product["id"])
    assert await call(m.get_task, tasks[0]["id"]) is None
    assert await call(m.get_task, tasks[1]["id"])


@pytest.mark.asyncio
async def test_project_cascade_and_parent_visibility_before_pagination(db):
    m = manager(db)
    product = await call(m.create, name="SDK")
    project = await call(m.create_project, product_id=product["id"], name="Release")
    await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    old = await call(m.create_task, product_id=product["id"], title="Old", project_id=project["id"])
    await call(m.delete_task, old["id"])
    task = await call(m.create_task, product_id=product["id"], title="New", project_id=project["id"])
    independent = await call(
        db.create_task,
        dict(
            id="legacy-independent",
            product_id=product["id"],
            title="Independent",
            status="backlog",
            created_at=1,
            transitions=[],
        ),
    )
    await call(m.delete_project, project["id"])
    assert (await call(m.get_task, task["id"], include_deleted=True))["transitions"][-1]["archived_by"] == {
        "type": "project",
        "id": project["id"],
    }
    for include_deleted in [False, True]:
        rows, total = await call(m.list_tasks, include_deleted=include_deleted, limit=1)
        assert total == 1 and rows[0]["id"] == independent["id"]
        assert await call(m.list_tasks, project_id=project["id"], include_deleted=include_deleted) == ([], 0)
        assert await call(m.list_tasks, include_deleted=include_deleted, limit=1, page=2) == ([], 1)
    assert (await call(m.list_projects, include_deleted=True))[1] == 1
    await call(m.restore_project, project["id"])
    assert await call(m.get_task, task["id"])
    assert await call(m.get_task, old["id"]) is None
    assert (await call(m.list_tasks, include_deleted=True))[1] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_type", ["product", "project"])
async def test_http_refuses_all_active_work_then_cascades_and_restores(db, parent_type):
    m = manager(db)
    product = await call(m.create, name="SDK")
    project = await call(m.create_project, product_id=product["id"], name="Release")
    await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    active = []
    for target in ["ready", "in_progress", "in_review"]:
        task = await call(m.create_task, product_id=product["id"], title=target, project_id=project["id"])
        for state in ["ready", "in_progress", "in_review"]:
            await call(
                m.transition_task,
                task_id=task["id"],
                target=state,
                reason="Advance",
                **({"executor_type": "agent", "executor_id": "writer"} if state == "ready" else {}),
            )
            if state == target:
                break
        active.append(task)
    backlog = await call(m.create_task, product_id=product["id"], title="Backlog", project_id=project["id"])
    # Legacy Task rows without a Project remain readable and participate in cascades.
    if parent_type == "product":
        independent = await call(
            db.create_task,
            dict(
                id="legacy-independent",
                product_id=product["id"],
                title="Independent",
                status="backlog",
                created_at=1,
                transitions=[],
            ),
        )
        await call(
            m.transition_task,
            task_id=independent["id"],
            target="ready",
            reason="Accept",
            executor_type="agent",
            executor_id="writer",
        )
        active.append(independent)
    parent = product if parent_type == "product" else project
    path = "/company/" + parent_type + "s/" + parent["id"]
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path + "/archive")
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["tasks"] == sorted(
            [{"id": t["id"], "title": t["title"]} for t in active], key=lambda t: t["id"]
        )
        assert (await client.get(path)).status_code == 200
        assert (await call(m.get_task, backlog["id"]))["deleted_at"] is None
        for task in active:
            await call(m.transition_task, task_id=task["id"], target="cancelled", reason="Stop")
        assert (await client.post(path + "/archive")).status_code == 200
        for include_deleted in [False, True]:
            response = await client.get("/company/tasks", params={"include_deleted": include_deleted})
            assert response.json()["data"] == []
            assert response.json()["meta"]["total_count"] == 0
            if parent_type == "product":
                response = await client.get("/company/projects", params={"include_deleted": include_deleted})
                assert response.json()["data"] == []
        response = await client.get("/company/" + parent_type + "s", params={"include_deleted": True})
        assert response.json()["data"][0]["id"] == parent["id"]
        assert (await client.post(path + "/restore")).status_code == 200
        assert (await call(m.list_tasks))[1] == len(active) + 1


@pytest.mark.asyncio
async def test_backlog_patch_move_and_cross_product_refusal(db):
    m = manager(db)
    product = await call(m.create, name="SDK")
    projects = [await call(m.create_project, product_id=product["id"], name=name) for name in ["One", "Two"]]
    for project in projects:
        await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    other_product = await call(m.create, name="Other")
    other = await call(m.create_project, product_id=other_product["id"], name="Other")
    task = await call(m.create_task, product_id=product["id"], title="Move", project_id=projects[0]["id"])
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path = "/company/tasks/" + task["id"]
        moved = await client.patch(path, json={"project_id": projects[1]["id"]})
        assert moved.status_code == 200, moved.text
        assert moved.json()["project_id"] == projects[1]["id"]
        assert moved.json()["product_id"] == product["id"]
        refused = await client.patch(path, json={"project_id": other["id"]})
        assert refused.status_code == 422
        assert "same Product" in refused.text
        with pytest.raises(ValueError, match="same Product"):
            await call(db.update_task, task["id"], project_id=other["id"])
        await call(m.delete_project, projects[0]["id"])
        assert await call(m.get_task, task["id"])
        assert (await client.patch(path, json={"project_id": projects[0]["id"]})).status_code == 404
        await call(m.delete_project, projects[1]["id"])
        await call(m.restore_project, projects[1]["id"])
        assert (await call(m.get_task, task["id"]))["project_id"] == projects[1]["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["archive", "restore"])
async def test_cascade_failure_rolls_back_parent_children_and_provenance(db, monkeypatch, operation):
    import agno.db.sql.company as archive

    m = manager(db)
    product = await call(m.create, name="SDK")
    project = await call(m.create_project, product_id=product["id"], name="Release")
    await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    task = await call(m.create_task, product_id=product["id"], title="Work", project_id=project["id"])
    if operation == "restore":
        await call(m.delete, product["id"])

    async def snapshot():
        return [
            await call(get, row["id"], include_deleted=True)
            for get, row in [(m.get, product), (m.get_project, project), (m.get_task, task)]
        ]

    before = await snapshot()
    original = getattr(archive, "_" + operation + "_children")

    def fail_after_child_write(*args):
        original(*args)
        raise RuntimeError("injected failure after child write")

    monkeypatch.setattr(archive, "_" + operation + "_children", fail_after_child_write)
    with pytest.raises(RuntimeError, match="injected"):
        await call(m.delete if operation == "archive" else m.restore, product["id"])
    assert await snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_type", ["product", "project"])
@pytest.mark.parametrize("winner", ["archive", "accept"])
async def test_acceptance_racing_archive_never_hides_active_work(db, parent_type, winner, monkeypatch):
    import asyncio
    from contextvars import ContextVar
    from threading import Event

    from sqlalchemy import event
    from sqlalchemy.util import await_only

    m = manager(db)
    app = AgentOS(
        db=db, agents=[Agent(id="writer", telemetry=False)], company=CompanyConfig(), telemetry=False
    ).get_app()
    product = await call(m.create, name="SDK")
    project = await call(m.create_project, product_id=product["id"], name="Release")
    await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    task = await call(m.create_task, product_id=product["id"], title="Race", project_id=project["id"])
    parent = product if parent_type == "product" else project
    path = "/company/tasks/" + task["id"]
    payload = {"target": "ready", "reason": "Accept", "executor_type": "agent", "executor_id": "writer"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # The same HTTP app must accept valid work before the concurrency probe.
        response = await client.post(path + "/transitions", json=payload)
        assert response.status_code == 200, response.text
        response = await client.post(path + "/transitions", json={"target": "backlog", "reason": "Replan"})
        assert response.status_code == 200, response.text

        actor = ContextVar("archive_race_actor", default=None)
        winner_locked, loser_at_lock = Event(), Event()

        def wrap(method, name):
            if isinstance(db, AsyncBaseDb):

                async def asynchronous(*args, **kwargs):
                    token = actor.set(name)
                    try:
                        return await method(*args, **kwargs)
                    finally:
                        actor.reset(token)

                return asynchronous

            def synchronous(*args, **kwargs):
                token = actor.set(name)
                try:
                    return method(*args, **kwargs)
                finally:
                    actor.reset(token)

            return synchronous

        archive_method = "delete_product" if parent_type == "product" else "delete_project"
        monkeypatch.setattr(db, archive_method, wrap(getattr(db, archive_method), "archive"))
        monkeypatch.setattr(db, "transition_task", wrap(db.transition_task, "accept"))
        engine = db.db_engine.sync_engine if isinstance(db, AsyncBaseDb) else db.db_engine

        def product_write(context):
            stmt = context.compiled.statement if context.compiled is not None else None
            return (
                actor.get() is not None
                and getattr(stmt, "is_update", False)
                and stmt.table.name == db.products_table_name
            )

        def wait(signal):
            # Async SQL events run inside the driver's greenlet: yield the loop while holding the lock.
            ready = await_only(asyncio.to_thread(signal.wait, 10)) if isinstance(db, AsyncBaseDb) else signal.wait(10)
            assert ready, "Both mutations must reach the Product lock"

        def before(conn, cursor, statement, parameters, context, executemany):
            if product_write(context) and actor.get() != winner:
                loser_at_lock.set()
                wait(winner_locked)

        def after(conn, cursor, statement, parameters, context, executemany):
            if product_write(context) and actor.get() == winner:
                winner_locked.set()
                wait(loser_at_lock)

        event.listen(engine, "before_cursor_execute", before)
        event.listen(engine, "after_cursor_execute", after)
        try:
            archived, accepted = await asyncio.wait_for(
                asyncio.gather(
                    client.post("/company/" + parent_type + "s/" + parent["id"] + "/archive"),
                    client.post(path + "/transitions", json=payload),
                ),
                timeout=30,
            )
        finally:
            event.remove(engine, "before_cursor_execute", before)
            event.remove(engine, "after_cursor_execute", after)
        assert winner_locked.is_set() and loser_at_lock.is_set()
        saved = await call(m.get_task, task["id"], include_deleted=True)
        if winner == "archive":
            assert archived.status_code == 200, archived.text
            assert accepted.status_code in [404, 409], accepted.text
            assert "missing from the registry" not in accepted.text
            assert saved["deleted_at"] is not None and saved["status"] == "backlog"
        else:
            assert accepted.status_code == 200, accepted.text
            assert archived.status_code == 409, archived.text
            assert archived.json()["detail"]["tasks"] == [{"id": task["id"], "title": task["title"]}]
            assert saved["deleted_at"] is None and saved["status"] == "ready"


@pytest.mark.asyncio
async def test_lists_hide_legacy_children_without_cascade_provenance(db, monkeypatch):
    import agno.db.sql.company as archive

    m = manager(db)
    product = await call(m.create, name="Archived by an older release")
    project = await call(m.create_project, product_id=product["id"], name="Still active")
    await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    await call(m.create_task, product_id=product["id"], title="Still active", project_id=project["id"])
    monkeypatch.setattr(archive, "_archive_children", lambda *args: None)
    await call(m.delete, product["id"])
    for include_deleted in [False, True]:
        assert await call(m.list_projects, include_deleted=include_deleted) == ([], 0)
        assert await call(m.list_tasks, include_deleted=include_deleted) == ([], 0)
    assert (await call(m.get, product["id"], include_deleted=True))["counts"]["projects"] == 0
    assert (await call(m.get, product["id"], include_deleted=True))["counts"]["tasks"]["backlog"] == 0
    await call(m.restore, product["id"])
    await call(m.delete_project, project["id"])
    assert (await call(m.get, product["id"]))["counts"]["tasks"]["backlog"] == 0
    for include_deleted in [False, True]:
        assert await call(m.list_tasks, include_deleted=include_deleted) == ([], 0)


@pytest.mark.asyncio
async def test_response_counts_match_filtered_lists_and_exclude_archives(db):
    m = manager(db)
    product = await call(m.create, name="SDK")
    project = await call(m.create_project, product_id=product["id"], name="Release")
    await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    active_project = await call(m.create_project, product_id=product["id"], name="Active")
    await call(m.transition_project, project_id=active_project["id"], target="active", reason="Start")
    terminal_project = await call(m.create_project, product_id=product["id"], name="Cancelled")
    await call(m.transition_project, project_id=terminal_project["id"], target="cancelled", reason="Stop")
    archived_project = await call(m.create_project, product_id=product["id"], name="Archived")
    await call(m.transition_project, project_id=archived_project["id"], target="active", reason="Approved")
    await call(m.create_task, product_id=product["id"], title="Hidden by Project", project_id=archived_project["id"])
    await call(m.delete_project, archived_project["id"])
    statuses = ["backlog", "ready", "in_progress", "in_review", "done", "cancelled"]
    archived_active = []
    for status in statuses:
        for project_id in [project["id"], None]:
            await call(
                db.create_task,
                {
                    "id": uuid4().hex,
                    "product_id": product["id"],
                    "project_id": project_id,
                    "title": status,
                    "status": status,
                    "session_id": uuid4().hex,
                    "job_id": uuid4().hex,
                    "evidence": [{"url": "https://example.com/one"}, {"url": "https://example.com/two"}],
                    "result": {"status": "ERROR", "content": "Retained execution result"},
                    "created_at": 1,
                    "transitions": [],
                },
            )
        archived = await call(
            db.create_task,
            {
                "id": uuid4().hex,
                "product_id": product["id"],
                "project_id": project["id"],
                "title": "Archived " + status,
                "status": status,
                "created_at": 1,
                "transitions": [],
            },
        )
        await call(m.delete_task, archived["id"])
        if status in {"ready", "in_progress", "in_review"}:
            archived_active.append(archived)
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for resource, record, expected in [("products", product, 2), ("projects", project, 1)]:
            detail = (await client.get("/company/" + resource + "/" + record["id"])).json()
            listing = (await client.get("/company/" + resource)).json()["data"]
            assert next(row for row in listing if row["id"] == record["id"])["counts"] == detail["counts"]
            for status in statuses:
                filtered = await client.get(
                    "/company/tasks", params={resource[:-1] + "_id": record["id"], "status": status}
                )
                assert detail["counts"]["tasks"][status] == filtered.json()["meta"]["total_count"] == expected
            if resource == "products":
                assert detail["counts"]["projects"] == 2
        archived = (
            await client.get("/company/projects/" + archived_project["id"], params={"include_deleted": True})
        ).json()
        assert archived["counts"]["tasks"] == dict.fromkeys(statuses, 0)
        schema = (await client.get("/openapi.json")).json()["components"]["schemas"]
        assert "counts" in schema["ProductResponse"]["properties"]
        assert "counts" in schema["ProjectResponse"]["properties"]
        assert set(schema["TaskCounts"]["properties"]) == set(statuses)
    for status in ["ready", "in_progress", "in_review"]:
        for task in (await call(m.list_tasks, status=status))[0]:
            await call(m.transition_task, task_id=task["id"], target="cancelled", reason="Finish")
    # Counts hide archived children, but their active status still blocks a parent archive.
    for archived in archived_active:
        await call(m.restore_task, archived["id"])
        await call(m.transition_task, task_id=archived["id"], target="cancelled", reason="Finish archived work")
        await call(m.delete_task, archived["id"])
    await call(m.delete, product["id"])
    archived_counts = (await call(m.get, product["id"], include_deleted=True))["counts"]
    assert archived_counts == {"projects": 0, "tasks": dict.fromkeys(statuses, 0)}
    await call(m.restore, product["id"])
    assert (await call(m.get, product["id"]))["counts"]["projects"] == 2
    assert (await call(m.get, product["id"]))["counts"]["tasks"]["cancelled"] == 8


@pytest.mark.asyncio
async def test_counts_page_query_bound_and_5000_task_performance(db):
    from statistics import median
    from time import perf_counter

    from sqlalchemy import event

    m = manager(db)
    products = [await call(m.create, name="Product " + str(i)) for i in range(25)]
    projects = [await call(m.create_project, product_id=p["id"], name="Project") for p in products]
    for project in projects:
        await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    table = await call(db._get_table, table_type="tasks", create_table_if_not_found=True)
    task_rows = [
        {
            "id": str(i),
            "product_id": products[i % 25]["id"],
            "project_id": projects[i % 25]["id"],
            "title": "Task " + str(i),
            "status": "backlog",
            "created_at": i,
            "transitions": [],
        }
        for i in range(5000)
    ]
    if isinstance(db, AsyncBaseDb):
        async with db.async_session_factory() as sess, sess.begin():
            await sess.execute(table.insert(), task_rows)
        engine = db.db_engine.sync_engine
    else:
        with db.Session() as sess, sess.begin():
            sess.execute(table.insert(), task_rows)
        engine = db.db_engine
    # Table resolution and SQL compilation are warmed before measuring page cost.
    await call(m.list, limit=25)
    await call(m.list_projects, limit=25)
    await call(m.list_tasks, limit=25)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        rows, total = await call(m.list, limit=25)
        assert len(rows) == total == 25
        assert all(
            row["counts"]
            == {
                "projects": 1,
                "tasks": {
                    "backlog": 200,
                    "ready": 0,
                    "in_progress": 0,
                    "in_review": 0,
                    "done": 0,
                    "cancelled": 0,
                },
            }
            for row in rows
        )
        assert len(statements) == 3, statements  # total, page, one grouped counts query
        assert sum("GROUP BY" in statement for statement in statements) == 1
        statements.clear()
        project_rows, total = await call(m.list_projects, limit=25)
        assert len(project_rows) == total == 25
        assert all(row["counts"]["tasks"]["backlog"] == 200 for row in project_rows)
        assert len(statements) == 3, statements
        statements.clear()
        await call(m.list, limit=1)
        assert len(statements) == 3, statements  # query count is independent of page size
        app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            statements.clear()
            response = await client.get("/company/products", params={"limit": 25})
            assert response.status_code == 200 and len(response.json()["data"]) == 25
            assert len(statements) == 3, statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    for method in [m.list, m.list_projects, m.list_tasks]:
        durations = []
        for _ in range(12):
            started = perf_counter()
            await call(method, limit=25)
            durations.append(perf_counter() - started)
        elapsed = median(durations)
        print(type(db).__name__, method.__name__, "median ms", round(elapsed * 1000, 2))
        assert elapsed < 0.020, (type(db).__name__, method.__name__, durations)


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_type", ["product", "project"])
async def test_separately_archived_active_task_does_not_block_parent_archive(db, parent_type):
    # Archived Tasks are hidden from lists and counts, so a blocker there would leave no way to clear it.
    m = manager(db)
    product = await call(m.create, name="SDK")
    project = await call(m.create_project, product_id=product["id"], name="Release")
    await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    task = await call(m.create_task, product_id=product["id"], title="Archived", project_id=project["id"])
    await call(
        m.transition_task,
        task_id=task["id"],
        target="ready",
        reason="Accept",
        executor_type="agent",
        executor_id="writer",
    )
    await call(m.delete_task, task["id"])
    active = await call(m.create_task, product_id=product["id"], title="Still active", project_id=project["id"])
    await call(
        m.transition_task,
        task_id=active["id"],
        target="ready",
        reason="Accept",
        executor_type="agent",
        executor_id="writer",
    )
    method, parent = (m.delete, product) if parent_type == "product" else (m.delete_project, project)
    # A visible active Task still blocks, and only it is reported.
    with pytest.raises(ValueError) as error:
        await call(method, parent["id"])
    assert error.value.args[0]["tasks"] == [{"id": active["id"], "title": active["title"]}]
    await call(m.transition_task, task_id=active["id"], target="cancelled", reason="Stop")
    assert await call(method, parent["id"])
    # The separate archive keeps its own provenance, so the parent's restore leaves it archived.
    archived = await call(m.get_task, task["id"], include_deleted=True)
    assert archived["status"] == "ready"
    assert "archived_by" not in archived["transitions"][-1]
    await call(m.restore if parent_type == "product" else m.restore_project, parent["id"])
    assert await call(m.get_task, task["id"]) is None
    assert await call(m.get_task, active["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_type", ["product", "project"])
async def test_attention_excludes_archived_ancestors_with_execution_results(db, monkeypatch, parent_type):
    import agno.db.sql.company as archive

    m = manager(db)
    product = await call(m.create, name="SDK")
    project = await call(m.create_project, product_id=product["id"], name="Release")
    await call(m.transition_project, project_id=project["id"], target="active", reason="Approved")
    for status in ["backlog", "in_progress", "in_review"]:
        await call(
            db.create_task,
            {
                "id": uuid4().hex,
                "product_id": product["id"],
                "project_id": project["id"],
                "title": status,
                "status": status,
                "session_id": uuid4().hex,
                "job_id": uuid4().hex,
                "evidence": [{"url": "https://example.com/evidence"}],
                "result": {"status": "ERROR", "content": "Failed execution"},
                "created_at": 1,
                "transitions": [],
            },
        )
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for params in [{}, {"product_id": product["id"]}]:
            response = await client.get("/company/attention", params=params)
            assert response.status_code == 200, response.text
            assert response.json() == {"proposals": 1, "in_review": 1, "failed": 1}
        # Reproduce parents archived by older releases, with live children left behind.
        monkeypatch.setattr(archive, "_archive_children", lambda *args: None)
        monkeypatch.setattr(archive, "_refuse_open_tasks", lambda *args: None)
        method, parent = (m.delete, product) if parent_type == "product" else (m.delete_project, project)
        assert await call(method, parent["id"])
        for params in [{}, {"product_id": product["id"]}]:
            response = await client.get("/company/attention", params=params)
            assert response.json() == {"proposals": 0, "in_review": 0, "failed": 0}
        for include_deleted in [False, True]:
            response = await client.get("/company/tasks", params={"failed": True, "include_deleted": include_deleted})
            assert response.json()["data"] == []
        assert not any((await call(m.get, product["id"], include_deleted=True))["counts"]["tasks"].values())
        assert not any((await call(m.get_project, project["id"], include_deleted=True))["counts"]["tasks"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource,method,payload",
    [
        ("products", "create_product", {"name": "SDK"}),
        ("projects", "create_project", {"name": "Release"}),
    ],
)
async def test_argless_storage_value_error_remains_validation_error(db, monkeypatch, resource, method, payload):
    product = await call(manager(db).create, name="SDK")
    if resource == "projects":
        payload = {**payload, "product_id": product["id"]}

    def fail(*args, **kwargs):
        raise ValueError()

    async def afail(*args, **kwargs):
        raise ValueError()

    monkeypatch.setattr(db, method, afail if isinstance(db, AsyncBaseDb) else fail)
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/company/" + resource, json=payload)
        assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_purge_discovery_includes_archived_parents_without_changing_lists(db):
    m = manager(db)
    product = await call(m.create, name="Purge discovery")
    project = await call(m.create_project, product_id=product["id"], name="Archived project")
    task = await call(m.create_task, product_id=product["id"], project_id=project["id"], title="Hidden task")
    await call(m.delete, product["id"])
    assert await call(db.get_tasks, include_deleted=True) == ([], 0)
    rows, total = await call(db.get_tasks, product_id=product["id"], include_deleted=True, include_deleted_parents=True)
    assert total == 1 and rows == [await call(db.get_task, task["id"], include_deleted=True)]
    assert await call(db.get_tasks, include_deleted=True) == ([], 0)


@pytest.mark.asyncio
async def test_purge_run_read_distinguishes_missing_storage_from_empty_session(db):
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus
    from agno.session.agent import AgentSession

    assert await call(db.get_runs, session_id="missing", deserialize=False) == ([], 0)
    with pytest.raises(RuntimeError, match="runs"):
        await call(db.get_runs, session_id="missing", deserialize=False, raise_on_error=True)
    await call(db.upsert_session, AgentSession(session_id="retained-session", created_at=1, updated_at=1))
    await call(
        db.upsert_run,
        RunOutput(run_id="retained-run", status=RunStatus.completed, content="Retained"),
        session_id="retained-session",
    )
    assert await call(db.get_runs, session_id="missing", deserialize=False, raise_on_error=True) == ([], 0)
    rows, count = await call(db.get_runs, session_id="retained-session", deserialize=False, raise_on_error=True)
    assert count == 1 and rows[0]["run_id"] == "retained-run"


@pytest.mark.asyncio
async def test_purge_run_read_propagates_query_failure(db, monkeypatch):
    from sqlalchemy import event

    await call(db._get_table, table_type="runs", create_table_if_not_found=True)
    engine = db.db_engine.sync_engine if isinstance(db, AsyncBaseDb) else db.db_engine

    def unavailable(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            raise RuntimeError("run query unavailable")

    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        with pytest.raises(RuntimeError, match="run query unavailable"):
            await call(db.get_runs, deserialize=False, raise_on_error=True)
        # Preserve the existing non-strict behavior, including AsyncPostgres' empty fallback.
        if isinstance(db, AsyncPostgresDb):
            assert await call(db.get_runs, deserialize=False) == ([], 0)
        else:
            with pytest.raises(RuntimeError, match="run query unavailable"):
                await call(db.get_runs, deserialize=False)
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["product", "project", "task"])
@pytest.mark.parametrize("archived", [False, True])
async def test_purge_owned_rows_and_preserve_unrelated_data(db, target, archived):
    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus
    from agno.session.agent import AgentSession

    await call(db._get_table, table_type="schedules", create_table_if_not_found=True)
    m = manager(db)
    product = await call(m.create, name="Delete", user_id="owner")
    other = await call(m.create, name="Keep")
    project = await call(m.create_project, product_id=product["id"], name="Delete project")
    sibling = await call(m.create_project, product_id=product["id"], name="Sibling")
    task = await call(m.create_task, product_id=product["id"], project_id=project["id"], title="Task")
    archived_task = await call(m.create_task, product_id=product["id"], project_id=project["id"], title="Old task")
    await call(m.delete_task, archived_task["id"])
    legacy = await call(
        db.create_task,
        dict(id="legacy", product_id=product["id"], title="Legacy", status="backlog", created_at=1, transitions=[]),
    )
    # This isolated imported fixture has no session or historical executions.
    await reconcile_execution_provenance(db, legacy, [])
    source = await call(m.create_source, product_id=product["id"], type="markdown", reference="/tmp/manual.md")
    await call(m.delete_source, source["id"])
    await call(db.upsert_session, AgentSession(session_id="keep-session", created_at=1, updated_at=1))
    await call(db.upsert_run, RunOutput(run_id="keep-run", status=RunStatus.completed), session_id="keep-session")
    if archived:
        await call(m.delete, product["id"])
    record = {"product": product, "project": project, "task": task}[target]
    purge = getattr(m, "purge" if target == "product" else "purge_" + target)
    assert not await call(purge, record["id"], user_id="wrong-owner")
    assert await call(purge, record["id"])
    assert not await call(purge, record["id"])
    assert await call(db.get_task, task["id"], include_deleted=True) is None
    assert (await call(db.get_task, archived_task["id"], include_deleted=True) is None) == (target != "task")
    assert (await call(db.get_project, project["id"], include_deleted=True) is None) == (target != "task")
    assert (await call(db.get_project, sibling["id"], include_deleted=True) is None) == (target == "product")
    assert (await call(db.get_task, legacy["id"], include_deleted=True) is None) == (target == "product")
    assert (await call(db.get_source, source["id"], include_deleted=True) is None) == (target == "product")
    assert (await call(db.get_product, product["id"], include_deleted=True) is None) == (target == "product")
    assert await call(db.get_product, other["id"]) == {k: v for k, v in other.items() if k != "counts"}
    assert (await call(db.get_runs, session_id="keep-session", deserialize=False))[1] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["edit", "new_task", "move"])
async def test_purge_rejects_changed_task_snapshot(db, change):
    await call(db._get_table, table_type="schedules", create_table_if_not_found=True)
    m = manager(db)
    product = await call(m.create, name="Snapshot")
    project = await call(m.create_project, product_id=product["id"], name="Original")
    sibling = await call(m.create_project, product_id=product["id"], name="Destination")
    task = await call(m.create_task, product_id=product["id"], project_id=project["id"], title="Original")
    snapshot = [await call(db.get_task, task["id"])]
    if change == "edit":
        await call(m.update_task, task["id"], title="Changed")
    elif change == "new_task":
        await call(m.create_task, product_id=product["id"], project_id=project["id"], title="New")
    else:
        await call(m.update_task, task["id"], project_id=sibling["id"])
    before = await call(db.get_tasks, product_id=product["id"])
    with pytest.raises(ValueError, match="changed"):
        await call(m.purge_project, project["id"], expected_tasks=snapshot)
    assert await call(db.get_tasks, product_id=product["id"]) == before
    assert await call(db.get_project, project["id"]) is not None
    with pytest.raises(ValueError, match="changed"):
        await call(m.purge, product["id"], expected_tasks=[])


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("archived", [False, True])
async def test_purge_requires_verification_and_refuses_unfinished_reservation(db, terminal, archived):
    m = manager(db)
    product = await call(m.create, name="Execution")
    project = await call(m.create_project, product_id=product["id"], name="Work")
    task = await call(m.create_task, product_id=product["id"], project_id=project["id"], title="Attempt")
    ready = await call(
        m.transition_task,
        task_id=task["id"],
        target="ready",
        reason="Accept",
        executor_type="agent",
        executor_id="writer",
    )
    reserved = await call(db.start_task_run, task["id"], 1, ready["transitions"], run_db_id="original")
    if terminal:
        await call(
            db.complete_task_run, task["id"], reserved["job_id"], {"status": "ERROR", "run_id": reserved["job_id"]}
        )
    if archived:
        await call(m.delete_task, task["id"])
    saved = await call(db.get_task, task["id"], include_deleted=True)
    with pytest.raises(ValueError, match="verification|unfinished"):
        await call(m.purge_task, task["id"])
    assert await call(db.get_task, task["id"], include_deleted=True) == saved
    if terminal:
        assert await call(m.purge_task, task["id"], expected_tasks=[saved])
    else:
        with pytest.raises(ValueError, match="unfinished"):
            await call(m.purge_task, task["id"], expected_tasks=[saved])
        assert await call(db.get_task, task["id"], include_deleted=True) == saved


@pytest.mark.asyncio
@pytest.mark.parametrize("archived", [False, True])
async def test_purge_requires_matching_verified_routine_links(db, archived):
    m = manager(db)
    product = await call(m.create, name="Linked")
    await call(db.add_product_routine, product["id"], "old-routine")
    if archived:
        await call(m.delete, product["id"])
    saved = await call(db.get_product, product["id"], include_deleted=True)
    for ids in [(), ("different-routine",)]:
        with pytest.raises(ValueError, match="Routine"):
            await call(m.purge, product["id"], verified_routine_ids=ids)
        assert await call(db.get_product, product["id"], include_deleted=True) == saved
    assert await call(m.purge, product["id"], verified_routine_ids=("old-routine",))


@pytest.mark.asyncio
async def test_purge_child_delete_failure_rolls_back_every_row(db):
    from sqlalchemy import event

    await call(db._get_table, table_type="schedules", create_table_if_not_found=True)
    m = manager(db)
    product = await call(m.create, name="Rollback")
    project = await call(m.create_project, product_id=product["id"], name="Child")
    task = await call(m.create_task, product_id=product["id"], project_id=project["id"], title="Child")
    before = [
        await call(get, row["id"], include_deleted=True)
        for get, row in [(db.get_product, product), (db.get_project, project), (db.get_task, task)]
    ]
    engine = db.db_engine.sync_engine if isinstance(db, AsyncBaseDb) else db.db_engine

    def fail_after_delete(conn, cursor, statement, parameters, context, executemany):
        stmt = context.compiled.statement if context.compiled is not None else None
        if getattr(stmt, "is_delete", False) and stmt.table.name == db.tasks_table_name:
            raise RuntimeError("failure after Task removal")

    event.listen(engine, "after_cursor_execute", fail_after_delete)
    try:
        with pytest.raises(RuntimeError, match="failure after Task removal"):
            await call(m.purge, product["id"])
    finally:
        event.remove(engine, "after_cursor_execute", fail_after_delete)
    assert [
        await call(get, row["id"], include_deleted=True)
        for get, row in [(db.get_product, product), (db.get_project, project), (db.get_task, task)]
    ] == before


@pytest.mark.asyncio
async def test_purge_base_run_reader_cannot_claim_strict_support(db):
    from agno.db.base import BaseDb

    base = AsyncBaseDb if isinstance(db, AsyncBaseDb) else BaseDb
    assert await call(base.get_runs, db, deserialize=False) == ([], 0)
    with pytest.raises(NotImplementedError):
        await call(base.get_runs, db, deserialize=False, raise_on_error=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["products", "projects", "tasks"])
@pytest.mark.parametrize("fault,status", [("missing_table", 503), ("programming_error", 500)])
async def test_purge_storage_error_mapping_preserves_rows(db, monkeypatch, resource, fault, status):
    from sqlalchemy import event

    await call(db._get_table, table_type="schedules", create_table_if_not_found=True)
    m = manager(db)
    product = await call(m.create, name="Storage failure")
    project = await call(m.create_project, product_id=product["id"], name="Child")
    task = await call(m.create_task, product_id=product["id"], project_id=project["id"], title="Child")
    records = [(db.get_product, product), (db.get_project, project), (db.get_task, task)]
    before = [await call(get, row["id"], include_deleted=True) for get, row in records]
    target = dict(products=product, projects=project, tasks=task)[resource]
    path = "/company/" + resource + "/" + target["id"]
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    engine = db.db_engine.sync_engine if isinstance(db, AsyncBaseDb) else db.db_engine
    lookup = db._get_table
    unavailable = {"products": "sources", "projects": "tasks", "tasks": "projects"}[resource]
    method = "purge_" + resource[:-1]
    purge = getattr(db, method)

    def missing_table(*args, **kwargs):
        if kwargs.get("table_type") == unavailable and kwargs.get("create_table_if_not_found"):
            return None
        return lookup(*args, **kwargs)

    async def async_missing_table(*args, **kwargs):
        return await call(missing_table, *args, **kwargs)

    def purge_with_missing_table(*args, **kwargs):
        with monkeypatch.context() as patch:
            patch.setattr(db, "_get_table", missing_table)
            return purge(*args, **kwargs)

    async def async_purge_with_missing_table(*args, **kwargs):
        with monkeypatch.context() as patch:
            patch.setattr(db, "_get_table", async_missing_table)
            return await purge(*args, **kwargs)

    def fail_after_delete(conn, cursor, statement, parameters, context, executemany):
        stmt = context.compiled.statement if context.compiled is not None else None
        if getattr(stmt, "is_delete", False) and stmt.table.name == db.tasks_table_name:
            raise RuntimeError("failure after Task removal")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        if fault == "missing_table":
            monkeypatch.setattr(
                db, method, async_purge_with_missing_table if isinstance(db, AsyncBaseDb) else purge_with_missing_table
            )
        else:
            event.listen(engine, "after_cursor_execute", fail_after_delete)
        try:
            for _ in range(2):
                response = await client.delete(path)
                assert response.status_code == status, response.text
                assert [await call(get, row["id"], include_deleted=True) for get, row in records] == before
        finally:
            monkeypatch.setattr(db, method, purge)
            if fault == "programming_error":
                event.remove(engine, "after_cursor_execute", fail_after_delete)
        assert (await client.delete(path)).status_code == 204
        assert (await client.delete(path)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reservation", "child_creation", "execution"])
@pytest.mark.parametrize("winner", ["purge", "other"])
async def test_purge_serializes_with_reservation_and_child_creation(db, operation, winner):
    import asyncio
    from contextvars import ContextVar
    from threading import Event

    from sqlalchemy import event
    from sqlalchemy.util import await_only

    await call(db._get_table, table_type="schedules", create_table_if_not_found=True)
    m = manager(db)
    product = await call(m.create, name="Purge race")
    await call(m.create_source, product_id=product["id"], type="markdown", reference="/tmp/race.md")
    project = await call(m.create_project, product_id=product["id"], name="Work")
    task = await call(m.create_task, product_id=product["id"], project_id=project["id"], title="Original")
    if operation in {"reservation", "execution"}:
        task = await call(
            m.transition_task,
            task_id=task["id"],
            target="ready",
            reason="Accept",
            executor_type="agent",
            executor_id="writer",
        )
    if operation == "execution":
        # Starting and finishing an attempt gives the Task its durable session identity.
        reserved = await call(db.start_task_run, task["id"], 1, task["transitions"], run_db_id="original")
        task = await call(db.complete_task_run, task["id"], reserved["job_id"], {"status": "ERROR"})
    snapshot = [await call(db.get_task, task["id"])]
    actor = ContextVar("purge_race_actor", default=None)
    winner_locked, loser_at_lock = Event(), Event()
    engine = db.db_engine.sync_engine if isinstance(db, AsyncBaseDb) else db.db_engine

    def observed_write(context):
        stmt = context.compiled.statement if context.compiled is not None else None
        if actor.get() is None or not getattr(stmt, "is_update", False):
            return False
        table_name = db.products_table_name if operation == "child_creation" else db.tasks_table_name
        # SQLite's database-wide write lock stops the losing purge at its earlier Product UPDATE.
        if (
            operation in {"reservation", "execution"}
            and winner == "other"
            and actor.get() == "purge"
            and engine.dialect.name == "sqlite"
        ):
            table_name = db.products_table_name
        return stmt.table.name == table_name

    def wait(signal):
        ready = await_only(asyncio.to_thread(signal.wait, 10)) if isinstance(db, AsyncBaseDb) else signal.wait(10)
        assert ready, "Both mutations must reach their write lock"

    def before(conn, cursor, statement, parameters, context, executemany):
        if observed_write(context) and actor.get() != winner:
            loser_at_lock.set()

    def after(conn, cursor, statement, parameters, context, executemany):
        if observed_write(context) and actor.get() == winner and not winner_locked.is_set():
            winner_locked.set()
            wait(loser_at_lock)

    async def mutate(name):
        token = actor.set(name)
        try:
            if name == "purge":
                method = m.purge_task if operation != "child_creation" else m.purge
                args, kwargs = (
                    (task["id"] if operation != "child_creation" else product["id"],),
                    {"expected_tasks": snapshot},
                )
            elif operation == "execution":
                method, args, kwargs = (
                    db.acquire_task_execution,
                    (task["session_id"], "racing-run"),
                    {"expected_task_ids": [task["id"]]},
                )
            elif operation == "reservation":
                method, args, kwargs = (
                    db.start_task_run,
                    (task["id"], 1, task["transitions"]),
                    {"run_db_id": "original"},
                )
            else:
                method, args, kwargs = (
                    m.create_task,
                    (),
                    {"product_id": product["id"], "project_id": project["id"], "title": "New"},
                )
            try:
                if isinstance(db, AsyncBaseDb):
                    return await method(*args, **kwargs)
                return await asyncio.to_thread(method, *args, **kwargs)
            except (ValueError, LookupError) as error:
                return error
        finally:
            actor.reset(token)

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        first = asyncio.create_task(mutate(winner))
        assert await asyncio.to_thread(winner_locked.wait, 10), "Winner must hold its write lock"
        second = asyncio.create_task(mutate("other" if winner == "purge" else "purge"))
        results = await asyncio.wait_for(asyncio.gather(first, second), 30)
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
    purged, changed = results if winner == "purge" else results[::-1]
    assert winner_locked.is_set() and loser_at_lock.is_set()
    if winner == "purge":
        assert purged is True
        if operation == "execution":
            assert isinstance(changed, ValueError) and "identity changed" in str(changed)
        else:
            assert changed is None if operation == "reservation" else isinstance(changed, (ValueError, LookupError))
        assert await call(db.get_task, task["id"], include_deleted=True) is None
    else:
        assert isinstance(purged, ValueError) and "changed" in str(purged)
        assert changed == [task["id"]] if operation == "execution" else isinstance(changed, dict)
        saved = await call(db.get_task, task["id"], include_deleted=True)
        assert saved is not None
        if operation == "execution":
            assert saved["metadata"]["_agno_execution_claims"] == ["racing-run"]
        elif operation == "reservation":
            assert saved["status"] == "in_progress" and saved["job_id"] == changed["job_id"]
        else:
            assert (await call(db.get_tasks, product_id=product["id"]))[1] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("archived", [False, True])
async def test_sdk_purge_checks_unlinked_routine_catalog(db, archived):
    from agno.scheduler import ScheduleManager

    m = manager(db)
    schedules = ScheduleManager(db)
    for _ in range(2):
        product = await call(m.create, name="Routine dependency")
        schedule = await schedules.acreate(
            name="Unlinked routine",
            cron="",
            endpoint="/agents/writer/runs",
            enabled_on_create=False,
            provenance={"managed_by": "company"},
            payload={"metadata": {"product_id": product["id"], **({"deleted_at": 1} if archived else {})}},
        )
        before = await call(db.get_product, product["id"])
        with pytest.raises(ValueError, match="Routine"):
            await call(m.purge, product["id"])
        assert await call(db.get_product, product["id"]) == before
        assert await schedules.aget(schedule.id) is not None
        assert await schedules.adelete(schedule.id)
        assert await call(m.purge, product["id"])
        assert not await call(m.purge, product["id"])


@pytest.mark.asyncio
async def test_sdk_purge_refuses_unavailable_schedule_catalog(db, monkeypatch):
    m = manager(db)
    product = await call(m.create, name="Unknown catalog", user_id="owner")
    before = await call(db.get_product, product["id"])

    def fail(*args, **kwargs):
        raise RuntimeError("Catalog read failed")

    async def afail(*args, **kwargs):
        return fail(*args, **kwargs)

    monkeypatch.setattr(db, "get_schedules", afail if isinstance(db, AsyncBaseDb) else fail)
    assert not await call(m.purge, product["id"], user_id="other")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="Catalog read failed"):
            await call(m.purge, product["id"])
        assert await call(db.get_product, product["id"]) == before


@pytest.mark.asyncio
async def test_raw_product_purge_requires_explicit_catalog_verification(db):
    product = await call(manager(db).create, name="Unverified")
    for _ in range(2):
        with pytest.raises(ValueError, match="Routine"):
            await call(db.purge_product, product["id"])
        assert await call(db.get_product, product["id"]) is not None
    assert await call(db.purge_product, product["id"], verified_routine_ids=())


@pytest.mark.asyncio
async def test_sdk_purge_preserves_unrelated_routine(db):
    from agno.scheduler import ScheduleManager

    m = manager(db)
    schedules = ScheduleManager(db)
    other = await call(m.create, name="Keep")
    routine = await schedules.acreate(
        name="Other Product routine",
        cron="",
        endpoint="/agents/writer/runs",
        enabled_on_create=False,
        provenance={"managed_by": "company"},
        payload={"metadata": {"product_id": other["id"]}},
    )
    for _ in range(2):
        product = await call(m.create, name="Delete")
        assert await call(m.purge, product["id"])
        assert await call(db.get_product, other["id"]) is not None
        assert await schedules.aget(routine.id) is not None


async def execution_task(db, metadata=None):
    m = manager(db)
    product = await call(m.create, name="Execution guard")
    project = await call(m.create_project, product_id=product["id"], name="Guarded project")
    task = await call(
        db.create_task,
        dict(
            id=uuid4().hex,
            product_id=product["id"],
            project_id=project["id"],
            title="Guarded task",
            status="backlog",
            session_id=uuid4().hex,
            created_at=1,
            updated_at=2,
            transitions=[],
            metadata=metadata,
        ),
    )
    return m, product, project, task


@pytest.mark.asyncio
@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("metadata", [None, {"note": "preserve", "checkout": {"ref": "main"}}])
@pytest.mark.parametrize("prepared", [False, True])
async def test_execution_claims_preserve_rows_and_release_only_their_token(db, archived, metadata, prepared):
    m, product, project, task = await execution_task(db, metadata)
    if archived:
        await call(m.delete, product["id"])
    before = await call(db.get_task, task["id"], include_deleted=True)
    session_id = task["session_id"]
    kwargs = {"expected_task_ids": [task["id"]]} if prepared else {}
    for cycle in range(2):
        first, second = f"first-{cycle}", f"second-{cycle}"
        assert await call(db.acquire_task_execution, session_id, first, **kwargs) == [task["id"]]
        assert await call(db.acquire_task_execution, session_id, first, **kwargs) == [task["id"]]
        assert await call(db.acquire_task_execution, session_id, second, **kwargs) == [task["id"]]
        claimed = await call(db.get_task, task["id"], include_deleted=True)
        assert set(claimed["metadata"]["_agno_execution_claims"]) == {first, second}
        assert claimed["metadata"]["_agno_execution_revision"] == (cycle + 1) * 2
        assert {k: v for k, v in claimed.items() if k != "metadata"} == {
            k: v for k, v in before.items() if k != "metadata"
        }
        assert {k: v for k, v in claimed["metadata"].items() if not k.startswith("_agno_execution_")} == (
            metadata or {}
        )
        await call(db.release_task_execution, session_id, first)
        await call(db.release_task_execution, session_id, first)
        remaining = await call(db.get_task, task["id"], include_deleted=True)
        assert remaining["metadata"]["_agno_execution_claims"] == [second]
        await call(db.release_task_execution, session_id, second)
        released = await call(db.get_task, task["id"], include_deleted=True)
        assert "_agno_execution_claims" not in released["metadata"]
        assert released["metadata"]["_agno_execution_revision"] == (cycle + 1) * 2
    assert await call(db.acquire_task_execution, "unrelated-session", "unrelated") == []
    await call(db.release_task_execution, "unrelated-session", "unrelated")
    assert await call(db.get_task, task["id"], include_deleted=True) == released


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["missing", "extra", "empty"])
async def test_prepared_execution_identity_mismatch_keeps_all_rows_unchanged(db, mismatch):
    metadata = {"note": "keep", "_agno_execution_claims": ["existing"], "_agno_execution_revision": 3}
    m, product, project, task = await execution_task(db, metadata)
    sibling = await call(db.create_task, {**task, "id": uuid4().hex, "metadata": None})
    await call(m.delete_task, sibling["id"])
    ids = [task["id"], sibling["id"]]
    expected = {"missing": ids[:1], "extra": [*ids, "absent"], "empty": []}[mismatch]
    before = [await call(db.get_task, task_id, include_deleted=True) for task_id in ids]
    for cycle in range(2):
        with pytest.raises(ValueError, match="Task execution identity changed"):
            await call(db.acquire_task_execution, task["session_id"], f"new-{cycle}", expected_task_ids=expected)
        assert [await call(db.get_task, task_id, include_deleted=True) for task_id in ids] == before
    # Identity is a set; caller order and duplicate IDs do not change which rows are protected.
    assert set(
        await call(db.acquire_task_execution, task["session_id"], "matched", expected_task_ids=[*ids[::-1], ids[0]])
    ) == set(ids)
    for task_id in ids:
        assert (
            "matched" in (await call(db.get_task, task_id, include_deleted=True))["metadata"]["_agno_execution_claims"]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["product", "project", "task"])
@pytest.mark.parametrize("archived", [False, True])
async def test_purge_refuses_execution_claim_even_in_verified_snapshot(db, target, archived):
    await call(db._get_table, table_type="schedules", create_table_if_not_found=True)
    m, product, project, task = await execution_task(db)
    await reconcile_execution_provenance(db, task, [])
    await call(db.acquire_task_execution, task["session_id"], "live")
    if archived:
        await call(m.delete, product["id"])
    snapshot = [await call(db.get_task, task["id"], include_deleted=True)]
    purge = getattr(m, "purge" if target == "product" else "purge_" + target)
    record = {"product": product, "project": project, "task": task}[target]
    for _ in range(2):
        with pytest.raises(ValueError, match="execution"):
            await call(purge, record["id"], expected_tasks=snapshot)
        assert await call(db.get_task, task["id"], include_deleted=True) == snapshot[0]


@pytest.mark.asyncio
async def test_execution_revision_prevents_snapshot_aba_and_unverified_purge(db):
    m, product, project, task = await execution_task(db)
    await reconcile_execution_provenance(db, task, [])
    snapshot = [await call(db.get_task, task["id"])]
    for token in ("first", "second"):
        await call(db.acquire_task_execution, task["session_id"], token)
        await call(db.release_task_execution, task["session_id"], token)
        with pytest.raises(ValueError, match="changed"):
            await call(m.purge_task, task["id"], expected_tasks=snapshot)
        with pytest.raises(ValueError, match="verification"):
            await call(m.purge_task, task["id"])
    current = await call(db.get_task, task["id"])
    assert await call(m.purge_task, task["id"], expected_tasks=[current])
    for _ in range(2):
        with pytest.raises(ValueError, match="Task execution identity changed"):
            await call(db.acquire_task_execution, task["session_id"], "prepared", expected_task_ids=[task["id"]])
        assert await call(db.acquire_task_execution, task["session_id"], "after-delete") == []
        assert await call(db.acquire_task_execution, task["session_id"], "empty", expected_task_ids=[]) == []
    await call(db.release_task_execution, task["session_id"], "second")


@pytest.mark.asyncio
async def test_execution_claims_are_private_in_http_and_public_task(db):
    from agno.db.schemas.tasks import public_task

    metadata = {"note": "public", "_agno_execution_claims": ["private-token"], "_agno_execution_revision": 3}
    m, product, project, task = await execution_task(db, metadata)
    registry = Registry(agents=[Agent(id="writer", telemetry=False)])
    app = AgentOS(db=db, registry=registry, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            response = await client.get("/company/tasks/" + task["id"])
            assert response.status_code == 200
            assert response.json()["metadata"] == {"note": "public"}
            listed = await client.get("/company/tasks", params={"product_id": product["id"]})
            assert listed.status_code == 200
            assert listed.json()["data"][0]["metadata"] == {"note": "public"}
    assert public_task(task)["metadata"] == {"note": "public"}
    assert task["metadata"] == metadata
    assert (await call(db.get_task, task["id"]))["metadata"] == metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["acquire_task_execution", "release_task_execution"])
async def test_execution_claims_fail_closed_when_task_table_is_unavailable(db, monkeypatch, operation):
    from agno.db.base import CompanyDeletionUnavailableError

    await execution_task(db)
    original = db._get_table

    def unavailable(*args, **kwargs):
        return None if kwargs.get("table_type") == "tasks" else original(*args, **kwargs)

    async def aunavailable(*args, **kwargs):
        return None if kwargs.get("table_type") == "tasks" else await original(*args, **kwargs)

    monkeypatch.setattr(db, "_get_table", aunavailable if isinstance(db, AsyncBaseDb) else unavailable)
    for _ in range(2):
        with pytest.raises(CompanyDeletionUnavailableError, match="execution"):
            await call(getattr(db, operation), "session", "token")


@pytest.mark.asyncio
async def test_execution_claim_survives_concurrent_checkout_completion(db):
    import asyncio
    from contextvars import ContextVar
    from threading import Event

    from sqlalchemy import event
    from sqlalchemy.util import await_only

    for cycle in range(2):
        m, product, project, task = await execution_task(db, {"note": "keep"})
        task = await call(
            m.transition_task,
            task_id=task["id"],
            target="ready",
            reason="Accepted",
            executor_type="agent",
            executor_id="writer",
        )
        task = await call(db.start_task_run, task["id"], 1, task["transitions"], run_db_id="runs")
        actor = ContextVar("checkout_claim_actor", default=None)
        completion_read, claim_attempted, claim_finished = Event(), Event(), Event()
        engine = db.db_engine.sync_engine if isinstance(db, AsyncBaseDb) else db.db_engine

        def wait(signal):
            ready = await_only(asyncio.to_thread(signal.wait, 10)) if isinstance(db, AsyncBaseDb) else signal.wait(10)
            assert ready, "Both mutations must reach the metadata read/write boundary"

        def before(conn, cursor, statement, parameters, context, executemany):
            stmt = context.compiled.statement if context.compiled is not None else None
            if actor.get() == "claim" and getattr(stmt, "is_update", False) and stmt.table.name == db.tasks_table_name:
                claim_attempted.set()

        def after(conn, cursor, statement, parameters, context, executemany):
            stmt = context.compiled.statement if context.compiled is not None else None
            if actor.get() != "complete" or completion_read.is_set() or stmt is None:
                return
            reads_task = getattr(stmt, "is_select", False) and any(
                table.name == db.tasks_table_name for table in stmt.get_final_froms()
            )
            locks_task = getattr(stmt, "is_update", False) and stmt.table.name == db.tasks_table_name
            if not (reads_task or locks_task):
                return
            completion_read.set()
            # An unlocked read lets the claim commit first, exposing a stale JSON merge.
            # A locking read instead makes the claimant wait until completion commits.
            locked = locks_task or getattr(stmt, "_for_update_arg", None) is not None
            wait(claim_attempted if locked else claim_finished)

        async def mutate(name):
            marker = actor.set(name)
            try:
                if name == "claim":
                    method, args, kwargs = db.acquire_task_execution, (task["session_id"], f"run-{cycle}"), {}
                else:
                    method, args, kwargs = (
                        db.complete_task_run,
                        (task["id"], task["job_id"], {"status": "COMPLETED"}),
                        {"checkout": {"ref": "completed"}},
                    )
                if isinstance(db, AsyncBaseDb):
                    return await method(*args, **kwargs)
                return await asyncio.to_thread(method, *args, **kwargs)
            finally:
                if name == "claim":
                    claim_finished.set()
                actor.reset(marker)

        event.listen(engine, "before_cursor_execute", before)
        event.listen(engine, "after_cursor_execute", after)
        try:
            completion = asyncio.create_task(mutate("complete"))
            assert await asyncio.to_thread(completion_read.wait, 10)
            acquisition = asyncio.create_task(mutate("claim"))
            await asyncio.wait_for(asyncio.gather(completion, acquisition), 30)
        finally:
            event.remove(engine, "before_cursor_execute", before)
            event.remove(engine, "after_cursor_execute", after)
        saved = await call(db.get_task, task["id"])
        assert saved["metadata"] == {
            "note": "keep",
            "checkout": {"ref": "completed"},
            "_agno_execution_claims": [f"run-{cycle}"],
            "_agno_execution_revision": 1,
        }


@pytest.mark.asyncio
async def test_execution_claims_are_private_in_edit_tool_results(db):
    import json

    from agno.run import RunContext
    from agno.tools.company import CompanyTools

    metadata = {"note": "public", "_agno_execution_claims": ["private-token"], "_agno_execution_revision": 3}
    m, product, project, task = await execution_task(db, metadata)
    tools = CompanyTools(db)
    edit = tools.aedit_company_task if isinstance(db, AsyncBaseDb) else tools.edit_company_task
    context = RunContext(run_id="human-edit", session_id="chat", user_id="owner")
    for title in ("Edited once", "Edited twice"):
        result = json.loads(await call(edit, task["id"], title, "Updated brief", _agno_run_context=context))
        assert result["title"] == title
        assert result["metadata"] == {"note": "public"}
        assert (await call(db.get_task, task["id"]))["metadata"] == metadata


async def reconcile_execution_provenance(db, task, stores):
    from agno.db.sql.company import _reconcile_task_execution_provenance

    table = await call(db._get_table, table_type="tasks")
    if isinstance(db, AsyncBaseDb):
        async with db.async_session_factory() as session, session.begin():
            await session.run_sync(_reconcile_task_execution_provenance, table, task, stores)
    else:
        with db.Session() as session, session.begin():
            _reconcile_task_execution_provenance(session, table, task, stores)


@pytest.mark.asyncio
async def test_execution_provenance_legacy_requires_offline_verification(db):
    m, _, _, task = await execution_task(db, {"note": "retained"})
    for _ in range(2):
        with pytest.raises(ValueError, match="provenance"):
            await call(m.purge_task, task["id"], expected_tasks=[task])
        assert await call(db.get_task, task["id"]) == task
    await reconcile_execution_provenance(db, task, [])
    verified = await call(db.get_task, task["id"])
    assert verified["metadata"] == {"note": "retained", "_agno_execution_provenance": {"complete": True, "stores": []}}
    assert await call(m.purge_task, task["id"], expected_tasks=[verified])


@pytest.mark.asyncio
async def test_execution_provenance_inventory_survives_release_without_certifying_legacy(db):
    m = manager(db)
    product = await call(m.create, name="Provenance")
    project = await call(m.create_project, product_id=product["id"], name="Project")
    fresh = await call(m.create_task, product_id=product["id"], project_id=project["id"], title="Fresh")
    _, _, _, legacy = await execution_task(db)
    stores = [dict(db_id=name, session_table="sessions", runs_table="runs") for name in ("original", "replacement")]
    for task, complete in [(fresh, True), (legacy, False)]:
        for cycle in range(2):
            for store in stores:
                await call(db.acquire_task_execution, task["session_id"], "run", execution_store=store)
            await call(db.release_task_execution, task["session_id"], "run")
            saved = await call(db.get_task, task["id"])
            assert saved["metadata"]["_agno_execution_provenance"] == {"complete": complete, "stores": stores}
            assert saved["metadata"]["_agno_execution_revision"] == cycle + 1
        await call(db.acquire_task_execution, task["session_id"], "unpersisted", execution_store={})
        await call(db.release_task_execution, task["session_id"], "unpersisted")
        await call(db.acquire_task_execution, task["session_id"], "persisted", execution_store=stores[0])
        await call(db.release_task_execution, task["session_id"], "persisted")
        assert (await call(db.get_task, task["id"]))["metadata"]["_agno_execution_provenance"]["complete"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["edit", "claim"])
async def test_execution_provenance_reconciliation_refuses_changed_or_claimed_row(db, change):
    _, _, _, task = await execution_task(db)
    if change == "edit":
        await call(db.update_task, task["id"], title="Concurrent edit")
    else:
        await call(db.acquire_task_execution, task["session_id"], "live")
    current = await call(db.get_task, task["id"])
    with pytest.raises(ValueError, match="changed|active"):
        await reconcile_execution_provenance(db, task if change == "edit" else current, [])
    assert await call(db.get_task, task["id"]) == current


@pytest.mark.asyncio
async def test_execution_provenance_is_private_and_cannot_be_supplied_over_http(db):
    import json

    from agno.db.schemas.tasks import public_task
    from agno.tools.company import _public_json

    metadata = {"note": "public", "_agno_execution_provenance": {"complete": True, "stores": []}}
    _, product, project, task = await execution_task(db, metadata)
    assert public_task(task)["metadata"] == {"note": "public"}
    assert json.loads(_public_json(task))["metadata"] == {"note": "public"}
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/company/tasks/" + task["id"])).json()["metadata"] == {"note": "public"}
        assert (await client.patch("/company/tasks/" + task["id"], json={"metadata": metadata})).status_code == 422
        response = await client.post(
            "/company/tasks",
            json={"product_id": product["id"], "project_id": project["id"], "title": "Forged", "metadata": metadata},
        )
        assert response.status_code == 422
    assert (await call(db.get_task, task["id"]))["metadata"] == metadata


@pytest.mark.asyncio
async def test_execution_provenance_reconciliation_preserves_recorded_stores_and_requires_runtime(db):
    m, _, _, task = await execution_task(db)
    original = {"db_id": "original", "session_table": "sessions", "runs_table": "runs"}
    replacement = {"db_id": "replacement", "session_table": "sessions", "runs_table": "runs"}
    await call(db.acquire_task_execution, task["session_id"], "old", execution_store=original)
    await call(db.release_task_execution, task["session_id"], "old")
    snapshot = await call(db.get_task, task["id"])
    await reconcile_execution_provenance(db, snapshot, [replacement])
    verified = await call(db.get_task, task["id"])
    assert verified["metadata"]["_agno_execution_provenance"] == {"complete": True, "stores": [original, replacement]}
    with pytest.raises(ValueError, match="verification"):
        await call(m.purge_task, task["id"])
    assert await call(db.get_task, task["id"]) == verified


@pytest.mark.asyncio
async def test_execution_provenance_offline_inventory_requires_runtime_even_without_revision(db):
    m, _, _, task = await execution_task(db)
    store = {"db_id": "historical", "session_table": "sessions", "runs_table": "runs"}
    await reconcile_execution_provenance(db, task, [store])
    verified = await call(db.get_task, task["id"])
    with pytest.raises(ValueError, match="verification"):
        await call(m.purge_task, task["id"])
    assert await call(db.get_task, task["id"]) == verified
