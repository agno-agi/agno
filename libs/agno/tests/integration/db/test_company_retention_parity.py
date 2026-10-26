"""Completion, retention and activity ordering on all four Company SQL adapters."""

import asyncio
import inspect
import json
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from agno.company import AsyncCompanyManager, CompanyManager
from agno.company.execution import _task_input
from agno.company.routines import _RoutineAuthorization
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.run.authorization import authorization_scope


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def archive(request, tmp_path):
    schema = "archive_" + uuid4().hex
    if "postgres" in request.param:
        cls = AsyncPostgresDb if request.param.startswith("async") else PostgresDb
        db = cls(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    else:
        cls = AsyncSqliteDb if request.param.startswith("async") else SqliteDb
        db = cls(db_file=str(tmp_path / "archive.db"))
    manager = AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db)

    async def call(receiver, method, /, *args, **kwargs):
        fn = getattr(receiver, method)
        return (
            await fn(*args, **kwargs)
            if inspect.iscoroutinefunction(fn)
            else await asyncio.to_thread(fn, *args, **kwargs)
        )

    yield db, manager, call
    await call(db, "close")
    if "postgres" in request.param:
        cleanup = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
        with cleanup.db_engine.begin() as conn:
            conn.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
        cleanup.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["backlog", "ready", "in_progress", "in_review"])
async def test_done_rejects_every_open_task_even_if_archived(archive, status):
    db, manager, call = archive
    product = await call(manager, "create", name="SDK")
    project = await call(manager, "create_project", product_id=product["id"], name="Ship")
    await call(manager, "transition_project", project_id=project["id"], target="active", reason="Begin")
    task = await call(
        db,
        "create_task",
        dict(
            id="open",
            product_id=product["id"],
            project_id=project["id"],
            title="Unfinished work",
            status=status,
            created_at=int(time.time()),
            transitions=[],
        ),
    )
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/company/projects/" + project["id"] + "/transitions", json={"target": "done", "reason": "Review"}
        )
        assert response.status_code == 409
        assert "Unfinished work" in response.text and task["id"] in response.text
    await call(manager, "delete_task", task["id"])
    for target in (manager, db):
        with pytest.raises(ValueError, match="Unfinished work"):
            await call(target, "transition_project", project_id=project["id"], target="done", reason="Review")
    await call(manager, "restore_task", task["id"])
    await call(db, "transition_task", task["id"], "cancelled", "No longer needed")
    assert (await call(manager, "transition_project", project_id=project["id"], target="done", reason="Reviewed"))[
        "status"
    ] == "done"


@pytest.mark.asyncio
async def test_refresh_proposes_once_and_cannot_accept(archive):
    db, manager, call = archive
    product = await call(manager, "create", name="SDK", user_id="owner")
    assert product["metadata"]["archive_window_days"] == 14
    project = await call(manager, "create_project", product_id=product["id"], name="Ship")
    await call(manager, "transition_project", project_id=project["id"], target="active", reason="Begin")
    task = await call(manager, "create_task", product_id=product["id"], title="Work", project_id=project["id"])
    assert not (await call(manager, "refresh", product["id"], user_id="owner"))["completion_proposals"]
    await call(manager, "transition_task", task_id=task["id"], target="cancelled", reason="Superseded")
    with authorization_scope(lambda: _RoutineAuthorization(None, "refresh")):
        first = await call(manager, "refresh", product["id"], user_id="owner")
        with pytest.raises(PermissionError, match="human"):
            await call(manager, "transition_project", project_id=project["id"], target="done", reason="Self acceptance")
    proposal = first["completion_proposals"][0]
    page = await call(manager, "read_wiki", product["id"], proposal["path"])
    assert "Proposed transition: Done" in page.content
    second = await call(manager, "refresh", product["id"], user_id="owner")
    assert second == first
    assert (await call(manager, "read_wiki", product["id"], proposal["path"])).metadata.version == page.metadata.version
    assert (await call(manager, "get_project", project["id"]))["status"] == "active"
    reopened = await call(manager, "create_task", product_id=product["id"], title="More work", project_id=project["id"])
    withdrawn = await call(manager, "refresh", product["id"])
    assert not withdrawn["completion_proposals"] and proposal["path"] in withdrawn["deleted_pages"]
    await call(manager, "transition_task", task_id=reopened["id"], target="cancelled", reason="Superseded")
    assert (await call(manager, "transition_project", project_id=project["id"], target="done", reason="Human review"))[
        "status"
    ] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("project_status", ["done", "cancelled"])
async def test_archive_window_paging_pages_context_and_restore(archive, monkeypatch, project_status):
    db, manager, call = archive
    now = int(time.time())
    old = now - 15 * 86400
    product = await call(manager, "create", name="SDK")
    other = await call(manager, "create", name="Other")
    project = await call(
        db,
        "create_project",
        dict(
            id="finished",
            product_id=product["id"],
            name="Finished",
            status=project_status,
            created_at=old,
            updated_at=old,
            transitions=[],
        ),
    )
    for i in range(105):
        await call(
            db,
            "create_task",
            dict(
                id=str(i),
                product_id=product["id"],
                project_id=project["id"],
                title="Old work",
                status="done" if i % 2 else "cancelled",
                created_at=old,
                updated_at=None,
                transitions=[],
            ),
        )
    for identifier, status, updated, pid in [
        ("open", "backlog", old, product["id"]),
        ("recent", "done", now, product["id"]),
        ("other", "done", old, other["id"]),
    ]:
        await call(
            db,
            "create_task",
            dict(
                id=identifier,
                product_id=pid,
                title=identifier,
                status=status,
                created_at=old,
                updated_at=updated,
                transitions=[],
            ),
        )
    monkeypatch.setattr(time, "time", lambda: old)
    for path, content in [
        ("summary.md", "Old generated report\n<!-- Company summary snapshot: e30= -->"),
        ("notes.md", "Keep human notes"),
    ]:
        await call(manager, "write_wiki", product_id=product["id"], path=path, content=content, expected_version=0)
    brief = await call(manager, "read_wiki", product["id"], "brief.md")
    status_page = await call(manager, "read_wiki", product["id"], "status.md")
    monkeypatch.setattr(time, "time", lambda: now)
    result = await call(manager, "refresh", product["id"])
    assert len(result["archived_tasks"]) == 0 and result["archived_projects"] == [project["id"]]
    assert result["deleted_pages"] == ["summary.md"]
    assert (await call(manager, "list_tasks", product_id=product["id"]))[1] == 2
    assert (await call(manager, "list_projects", product_id=product["id"]))[1] == 0
    assert await call(manager, "get_task", "0") is None
    assert (await call(manager, "get_task", "0", include_deleted=True))["deleted_at"] == now
    assert (await call(manager, "get_task", "other"))["deleted_at"] is None
    counts = await call(manager, "attention", product["id"])
    assert counts == {"proposals": 1, "in_review": 0, "failed": 0}
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert (await client.post("/company/tasks/0/runs")).status_code == 404
    active = await call(manager, "get_task", "open")
    context = json.loads(await _task_input(manager, active))
    assert not any(page["path"] == "summary.md" for page in context["wiki"])
    assert (await call(manager, "read_wiki", product["id"], "brief.md")).content == brief.content
    assert (await call(manager, "read_wiki", product["id"], "status.md")).content == status_page.content
    assert (await call(manager, "read_wiki", product["id"], "notes.md")).content == "Keep human notes"
    await call(manager, "restore_project", project["id"])
    assert (await call(manager, "list_tasks", project_id=project["id"], limit=200))[1] == 105
    again = await call(manager, "refresh", product["id"])
    assert not again["archived_tasks"] and not again["archived_projects"]
    assert not await call(manager, "delete_task", "open", updated_before=now)
    assert not await call(manager, "delete_task", "recent", updated_before=now)
    await call(manager, "update", product["id"], metadata={"archive_window_days": 30})
    assert (await call(manager, "refresh", product["id"]))["archive_window_days"] == 30


@pytest.mark.asyncio
async def test_retention_reuses_cascade_counts_and_exact_restore(archive):
    db, manager, call = archive
    now = int(time.time())
    product = await call(manager, "create", name="SDK")
    project = await call(
        db,
        "create_project",
        dict(
            id="old-project",
            product_id=product["id"],
            name="Finished",
            status="cancelled",
            created_at=now - 15 * 86400,
            updated_at=now - 15 * 86400,
            transitions=[],
        ),
    )
    for identifier in ("recent-child", "separate-child"):
        await call(
            db,
            "create_task",
            dict(
                id=identifier,
                product_id=product["id"],
                project_id=project["id"],
                title=identifier,
                status="done",
                created_at=now,
                updated_at=now,
                transitions=[],
            ),
        )
    await call(manager, "delete_task", "separate-child")
    assert (await call(manager, "get", product["id"]))["counts"]["tasks"]["done"] == 1
    result = await call(manager, "refresh", product["id"])
    assert result["archived_projects"] == [project["id"]]
    assert not result["archived_tasks"]  # The parent cascade owns this archive.
    assert (await call(manager, "list_tasks", product_id=product["id"], include_deleted=True))[1] == 0
    assert (await call(manager, "get", product["id"]))["counts"]["tasks"]["done"] == 0
    child = await call(manager, "get_task", "recent-child", include_deleted=True)
    assert child["transitions"][-1]["archived_by"] == {"type": "project", "id": project["id"]}
    await call(manager, "restore_project", project["id"])
    assert await call(manager, "get_task", "recent-child") is not None
    assert await call(manager, "get_task", "separate-child") is None
    assert (await call(manager, "get_project", project["id"]))["counts"]["tasks"]["done"] == 1


@pytest.mark.asyncio
async def test_retention_keeps_active_work_refusal(archive, monkeypatch):
    db, manager, call = archive
    old = int(time.time()) - 15 * 86400
    product = await call(manager, "create", name="SDK")
    project = await call(
        db,
        "create_project",
        dict(
            id="cancelled-project",
            product_id=product["id"],
            name="Cancelled",
            status="active",
            created_at=old,
            updated_at=old,
            transitions=[],
        ),
    )
    await call(
        db,
        "create_task",
        dict(
            id="active-child",
            product_id=product["id"],
            project_id=project["id"],
            title="Still running",
            status="in_progress",
            created_at=old,
            transitions=[],
        ),
    )
    monkeypatch.setattr(time, "time", lambda: old)
    await call(manager, "transition_project", project_id=project["id"], target="cancelled", reason="Stop project")
    monkeypatch.setattr(time, "time", lambda: old + 16 * 86400)
    with pytest.raises(ValueError) as refusal:
        await call(manager, "refresh", product["id"])
    assert refusal.value.args[0]["tasks"] == [{"id": "active-child", "title": "Still running"}]
    assert await call(manager, "get_project", project["id"]) is not None
    assert await call(manager, "get_task", "active-child") is not None


@pytest.mark.asyncio
async def test_deduplicated_insert_keeps_parent_archive_guards(archive):
    db, manager, call = archive
    product = await call(manager, "create", name="SDK")
    project = await call(manager, "create_project", product_id=product["id"], name="Work")
    fields = dict(
        id="proposal",
        product_id=product["id"],
        project_id=project["id"],
        title="Observed issue",
        status="backlog",
        dedupe_key="source-issue",
        created_at=int(time.time()),
        transitions=[],
    )
    await call(manager, "delete_project", project["id"])
    with pytest.raises(ValueError, match="Project is missing or archived"):
        await call(db, "create_task", fields)
    await call(manager, "restore_project", project["id"])
    await call(manager, "delete", product["id"])
    with pytest.raises(ValueError, match="Product is missing or archived"):
        await call(db, "create_task", fields)
    await call(manager, "restore", product["id"])
    first = await call(db, "create_task", fields)
    repeated = await call(db, "create_task", {**fields, "id": "another-id"})
    assert repeated["id"] == first["id"]
    assert (await call(manager, "get", product["id"]))["counts"]["tasks"]["backlog"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["products", "projects", "tasks"])
async def test_activity_sorting_precedes_paging(archive, domain):
    db, manager, call = archive
    parent = await call(manager, "create", name="Parent") if domain != "products" else None
    singular = domain[:-1]
    for identifier, created, updated in [("a", 10, 80), ("b", 20, None), ("c", 30, 60)]:
        fields = dict(id=identifier, created_at=created, updated_at=updated)
        if parent:
            fields.update(
                product_id=parent["id"], status="active" if domain == "projects" else "backlog", transitions=[]
            )
        fields["title" if domain == "tasks" else "name"] = identifier
        await call(db, "create_" + singular, fields)
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert [row["id"] for row in (await client.get("/company/" + domain)).json()["data"]] == ["c", "b", "a"]
        for order, expected in [("asc", ["b", "c", "a"]), ("desc", ["a", "c", "b"])]:
            ids = []
            for page in (1, 2, 3):
                response = await client.get(
                    "/company/" + domain,
                    params={"sort_by": "updated_at", "sort_order": order, "limit": 1, "page": page},
                )
                assert response.status_code == 200, response.text
                assert response.json()["meta"]["total_count"] == 3
                ids.append(response.json()["data"][0]["id"])
            assert ids == expected
        assert (await client.get("/company/" + domain, params={"sort_by": "private"})).status_code == 422
        assert (await client.get("/company/" + domain, params={"sort_order": "sideways"})).status_code == 422


@pytest.mark.asyncio
async def test_archive_policy_validation(archive):
    _, manager, call = archive
    for invalid in (-1, True, "14", 1.5):
        with pytest.raises(ValueError, match="archive_window_days"):
            await call(manager, "create", name="Invalid", metadata={"archive_window_days": invalid})


@pytest.mark.asyncio
async def test_custom_archive_window_and_exact_boundary(archive, monkeypatch):
    db, manager, call = archive
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now)
    product = await call(manager, "create", name="Long retention", metadata={"archive_window_days": 30})
    for identifier, age in [("expired", 31), ("boundary", 30), ("within", 15)]:
        await call(
            db,
            "create_task",
            dict(
                id=identifier,
                product_id=product["id"],
                title=identifier,
                status="cancelled",
                created_at=now - age * 86400,
                transitions=[],
            ),
        )
    result = await call(manager, "refresh", product["id"])
    assert result["archived_tasks"] == ["expired"]
    assert (await call(manager, "list_tasks", product_id=product["id"]))[1] == 2


@pytest.mark.asyncio
async def test_completion_proposal_does_not_reintroduce_archived_task_context(archive):
    db, manager, call = archive
    product = await call(manager, "create", name="SDK")
    project = await call(manager, "create_project", product_id=product["id"], name="Ship")
    await call(manager, "transition_project", project_id=project["id"], target="active", reason="Begin")
    await call(
        db,
        "create_task",
        dict(
            id="archived-task-private-detail",
            product_id=product["id"],
            project_id=project["id"],
            title="Old Task detail",
            status="done",
            created_at=int(time.time()) - 15 * 86400,
            transitions=[],
        ),
    )
    current_project = await call(manager, "create_project", product_id=product["id"], name="Current work")
    current = await call(
        manager,
        "create_task",
        product_id=product["id"],
        title="Current independent work",
        project_id=current_project["id"],
    )
    result = await call(manager, "refresh", product["id"])
    assert result["archived_tasks"] == ["archived-task-private-detail"]
    assert result["completion_proposals"][0]["project_id"] == project["id"]
    context = await _task_input(manager, current)
    assert "archived-task-private-detail" not in context
    assert "Old Task detail" not in context


@pytest.mark.asyncio
async def test_terminal_project_rejects_new_and_moved_open_work(archive):
    db, manager, call = archive
    product = await call(manager, "create", name="SDK")
    project = await call(manager, "create_project", product_id=product["id"], name="Ship")
    await call(manager, "transition_project", project_id=project["id"], target="active", reason="Start")
    await call(manager, "transition_project", project_id=project["id"], target="done", reason="Complete")
    with pytest.raises(ValueError, match="open work"):
        await call(manager, "create_task", product_id=product["id"], title="Late proposal", project_id=project["id"])
    open_project = await call(manager, "create_project", product_id=product["id"], name="Next release")
    task = await call(
        manager, "create_task", product_id=product["id"], title="Next release", project_id=open_project["id"]
    )
    with pytest.raises(ValueError, match="open work"):
        await call(manager, "update_task", task["id"], project_id=project["id"])
    assert (await call(manager, "get_task", task["id"]))["project_id"] == open_project["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_proposal", [False, True])
async def test_refresh_never_deletes_a_replaced_page(archive, monkeypatch, stale_proposal):
    from agno.fs import FileSystem

    db, manager, call = archive
    product = await call(manager, "create", name="SDK")
    path = "project-completion/old.md" if stale_proposal else "summary.md"
    content = (
        "<!-- Company completion proposal -->\nOld" if stale_proposal else "<!-- Company summary snapshot: e30= -->"
    )
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now - 15 * 86400)
    await call(manager, "write_wiki", product_id=product["id"], path=path, content=content, expected_version=0)
    monkeypatch.setattr(time, "time", lambda: now)
    original = FileSystem.adelete

    async def replaced(self, candidate, **kwargs):
        if candidate == path:
            await self.awrite(path, "Fresh human replacement", expected_version=1)
        return await original(self, candidate, **kwargs)

    monkeypatch.setattr(FileSystem, "adelete", replaced)
    result = await call(manager, "refresh", product["id"])
    assert path not in result["deleted_pages"]
    assert (await call(manager, "read_wiki", product["id"], path)).content == "Fresh human replacement"


@pytest.mark.asyncio
async def test_routine_mutations_are_bound_and_project_proposals_reuse(archive, tmp_path):
    db, manager, call = archive
    product = await call(manager, "create", name="Own")
    other = await call(manager, "create", name="Other")
    source = await call(
        manager, "create_source", product_id=other["id"], type="website", reference="https://example.com"
    )
    authority = _RoutineAuthorization(None, "routine", product_id=product["id"])
    with authorization_scope(lambda: authority):
        for method, kwargs in [
            ("create_project", {"product_id": other["id"], "name": "Intrusion"}),
            ("refresh", {"product_id": other["id"]}),
            (
                "write_wiki",
                {"product_id": other["id"], "path": "status.md", "content": "Intrusion", "expected_version": 0},
            ),
            ("read_source", {"source_id": source["id"], "run_id": "scan"}),
            (
                "add_source",
                {
                    "product_id": other["id"],
                    "type": "website",
                    "reference": "https://example.org",
                    "executor_id": "finder",
                    "executor_type": "agent",
                    "run_id": "scan",
                },
            ),
        ]:
            with pytest.raises(PermissionError, match="configured Product"):
                await call(manager, method, **kwargs)
        proposals = await asyncio.gather(
            *[call(manager, "create_project", product_id=product["id"], name="One proposal") for _ in range(3)]
        )
        assert len({row["id"] for row in proposals}) == 1
    await call(manager, "update_project", proposals[0]["id"], outcome="Human edit")
    await call(manager, "delete_project", proposals[0]["id"])
    with authorization_scope(lambda: authority):
        repeated = await call(manager, "create_project", product_id=product["id"], name="One proposal")
    assert repeated["deleted_at"] is not None and repeated["outcome"] == "Human edit"


@pytest.mark.asyncio
async def test_sources_hide_archived_parent_and_routine_links_preserve_metadata(archive):
    db, manager, call = archive
    product = await call(manager, "create", name="SDK", metadata={"archive_window_days": 30, "custom": "kept"})
    await call(manager, "create_source", product_id=product["id"], type="website", reference="https://example.com")
    await asyncio.gather(*[call(db, "add_product_routine", product["id"], str(i)) for i in range(4)])
    linked = await call(manager, "get", product["id"])
    assert set(linked["metadata"]["routine_ids"]) == {"0", "1", "2", "3"}
    assert linked["metadata"]["custom"] == "kept" and linked["metadata"]["archive_window_days"] == 30
    await call(manager, "delete", product["id"])
    assert (await call(manager, "list_sources", product_id=product["id"]))[1] == 0
    await call(manager, "restore", product["id"])
    assert (await call(manager, "list_sources", product_id=product["id"]))[1] == 1


@pytest.mark.asyncio
async def test_routine_link_repairs_sql_null_metadata(archive):
    from sqlalchemy import null

    db, manager, call = archive
    product = await call(manager, "create", name="Legacy")
    table = await call(db, "_get_table", table_type="products")
    statement = table.update().where(table.c.id == product["id"]).values(metadata=null())
    if isinstance(db, AsyncBaseDb):
        async with db.db_engine.begin() as connection:
            await connection.execute(statement)
    else:
        with db.db_engine.begin() as connection:
            connection.execute(statement)
    linked = await call(db, "add_product_routine", product["id"], "routine")
    assert linked["metadata"] == {"archive_window_days": 14, "routine_ids": ["routine"]}


@pytest.mark.asyncio
async def test_completed_project_preserves_intake_dedupe(archive):
    db, manager, call = archive
    product = await call(manager, "create", name="SDK")
    project = await call(manager, "create_project", product_id=product["id"], name="Ship")
    await call(manager, "transition_project", project_id=project["id"], target="active", reason="Start")
    fields = dict(
        id="proposal",
        title="Issue",
        product_id=product["id"],
        project_id=project["id"],
        dedupe_key="issue",
        status="backlog",
        created_at=int(time.time()),
        transitions=[],
    )
    await call(db, "create_task", fields)
    await call(manager, "transition_task", task_id="proposal", target="cancelled", reason="Resolved")
    await call(manager, "transition_project", project_id=project["id"], target="done", reason="Complete")
    assert (await call(db, "create_task", {**fields, "id": "repeat"}))["id"] == "proposal"
    with pytest.raises(ValueError, match="open work"):
        await call(db, "create_task", {**fields, "id": "new", "dedupe_key": "different"})
