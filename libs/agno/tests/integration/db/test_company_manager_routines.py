"""Manager Routines retain authority through the PostgreSQL durable queue."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from agno.company.execution import _call
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.company.routines import _CompanyScheduleExecutor, _RoutineAuthorization
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.job_queue import QueueConfig
from agno.os import AgentOS, Authorization, CompanyConfig, OSManager
from agno.os.job_queue import QueueWorker, resolve_queue_store
from agno.registry._reserved import COMPANY_MANAGER_ID, MANAGER_TEAM_ID
from agno.run import RunContext
from agno.run.authorization import current_authorization
from tests.integration.db.test_company_execution_parity import SimpleClient, execute
from tests.integration.db.test_company_playbook_parity import db as company_db
from tests.unit.os.routers.test_company_manager_routines import (
    SECRET,
    ScriptedModel,
    declaration,
    headers,
    review_steps,
)

db = company_db


@pytest.mark.parametrize("backend", ["sqlite", "async_sqlite", "postgres", "async_postgres"])
@pytest.mark.parametrize("mode", ["standalone", "member"])
async def test_manager_review_through_durable_queue(tmp_path, backend, mode):
    schema = "manager_routine_" + uuid4().hex
    queue_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    if backend == "postgres":
        db = queue_db
    elif backend == "async_postgres":
        db = AsyncPostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    else:
        cls = AsyncSqliteDb if backend == "async_sqlite" else SqliteDb
        db = cls(db_file=str(tmp_path / "company.db"))
    config = QueueConfig(durable=True, db=queue_db, max_attempts=1)
    os = AgentOS(
        id="routine-test",
        db=queue_db,
        company=CompanyConfig(db=db, model=ScriptedModel()),
        manager=OSManager(model=ScriptedModel(), access_docs=False, offload_tool_results=False)
        if mode != "standalone"
        else None,
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", audience="routine-test"),
        user_isolation=True,
        queue=config,
        telemetry=False,
    )
    app = os.get_app()
    components = {
        (kind, component.id): component
        for kind, entries in (("agent", os._agents), ("team", os._teams))
        for component in entries
    }
    worker = QueueWorker(
        resolve_queue_store(config, queue_db),
        lambda kind, cid, scope=None: components.get((kind, cid)),
        config,
        authorization_app=app,
    )
    worker._company_db = db
    app.state.queue_worker = worker
    manager = AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db)
    observed = []

    def observe_queue_authority(_agno_run_context: RunContext) -> str:
        authority = current_authorization()
        if not isinstance(authority, _RoutineAuthorization):
            raise RuntimeError("Routine authority lost at queue/delegation boundary")
        observed.append((_agno_run_context.user_id, authority.context.principal_id, authority.product_id))
        return "Restored authority observed"

    os.company_manager.tools.append(observe_queue_authority)
    try:
        product = await _call(manager, "create", name="Docs", user_id="alice")
        project = await _call(manager, "create_project", product_id=product["id"], name="Guides", user_id="alice")
        path = tmp_path / "source.md"
        path.write_text("The released API needs a guide.")
        source = await _call(manager, "create_source", product_id=product["id"], type="markdown", reference=str(path))
        os.company_manager.model = ScriptedModel(
            [("observe_queue_authority", {})] + review_steps(product, project, source, path)
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            jobs = []

            async def request_and_work(method, url, **kwargs):
                response = await client.request(method, url, **kwargs)
                if method == "POST" and response.status_code == 202:
                    job = await execute(worker)
                    jobs.append(job)
                return response

            executor = _CompanyScheduleExecutor(
                os,
                app,
                company_db=db,
                schedule_db=queue_db,
                base_url="http://test",
                internal_service_token=os._internal_service_token,
                poll_interval=0.01,
                timeout=10,
            )
            executor._get_client = AsyncMock(return_value=SimpleClient(request_and_work))
            response = await client.post(
                "/company/routines",
                headers=headers(),
                json={"product_id": product["id"], **declaration().model_dump()},
            )
            assert response.status_code == 201, response.text
            row = queue_db.get_schedule(response.json()["id"])
            result = await executor.execute(row, queue_db, release_schedule=False)
            assert result["status"] == "success", result
            assert len(jobs) == 1 and jobs[0]["status"] == "completed"
            assert jobs[0]["user_id"] == "alice"
            assert observed == [("alice", "alice", product["id"])]
            tasks, total = await _call(db, "get_tasks", product_id=product["id"])
            assert total == 1 and tasks[0]["status"] == "backlog"
            assert tasks[0]["user_id"] == "alice" and tasks[0]["routine_id"] == row["id"]
            assert tasks[0]["evidence"][0]["content_hash"]
            status = await _call(manager, "read_wiki", product["id"], "status.md")
            assert "API guide proposed" in status.content

            # An ERROR run row is not terminal admission while its ticket awaits retry.
            config.max_attempts = 2
            config.retry_delay_seconds = 0
            os.company_manager.model = ScriptedModel([("read_product_source", {"source_id": "missing"})])
            failed = await executor.execute(row, queue_db, release_schedule=False)
            assert failed["status"] == "failed", failed
            assert jobs[-1]["status"] == "queued"
            before = len(jobs)
            overlap = await executor.execute(row, queue_db, release_schedule=False)
            assert "Another Routine review" in overlap["error"], overlap
            assert len(jobs) == before
            os.company_manager.model = ScriptedModel()
            retried = await execute(worker)
            assert retried["status"] == "completed", retried
            later = await executor.execute(row, queue_db, release_schedule=False)
            assert later["status"] == "success", later
            assert (await _call(db, "get_tasks", product_id=product["id"]))[1] == 1
    finally:
        if db is not queue_db:
            if isinstance(db, AsyncBaseDb):
                await db.close()
            else:
                db.close()
        with queue_db.db_engine.begin() as connection:
            connection.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
        queue_db.close()


@pytest.mark.parametrize("mode", ["standalone", "member"])
@pytest.mark.parametrize("use_async", [False, True])
async def test_chat_declarations_use_owned_managers(db, use_async, mode, tmp_path):
    from tests.integration.db.test_company_chat_products import context, invoke

    if isinstance(db, AsyncBaseDb) and not use_async:
        pytest.skip("Sync tools require a sync database")
    os = AgentOS(
        db=db if not isinstance(db, AsyncBaseDb) else SqliteDb(db_file=str(tmp_path / "schedules.db")),
        company=CompanyConfig(db=db, model=ScriptedModel()),
        manager=OSManager(model=ScriptedModel(), access_docs=False) if mode != "standalone" else None,
        telemetry=False,
    )
    tools = os.company_manager.tools[0]
    with pytest.raises(ValueError, match="Only the Company Manager"):
        await invoke(
            tools,
            "create_company_product",
            use_async,
            name="Coordinated",
            routines=[declaration("team", MANAGER_TEAM_ID).model_dump()],
            _agno_run_context=context(),
        )
    assert (await _call(db, "get_products"))[1] == 0
    kind, cid = "agent", COMPANY_MANAGER_ID
    routine = declaration(kind, cid).model_dump()
    product = await invoke(
        tools, "create_company_product", use_async, name="Docs", routines=[routine], _agno_run_context=context()
    )
    saved = os.db.get_schedule(product["metadata"]["routine_ids"][0])
    assert saved["target_id"] == cid and saved["user_id"] == "ana"
    second = await invoke(
        tools,
        "create_product_routine",
        use_async,
        product_id=product["id"],
        **{**declaration(kind, cid).model_dump(exclude={"auto_accept"}), "name": "another-review"},
        _agno_run_context=context(),
    )
    assert second["target_id"] == cid
    with pytest.raises(ValueError, match="Only the Company Manager"):
        await invoke(
            tools,
            "create_product_routine",
            use_async,
            product_id=product["id"],
            **{**declaration("team", MANAGER_TEAM_ID).model_dump(exclude={"auto_accept"}), "name": "coordinated"},
            _agno_run_context=context(),
        )
    os._company_manager = None
    with pytest.raises(ValueError, match="unavailable"):
        await invoke(
            tools,
            "create_company_product",
            use_async,
            name="Unavailable",
            routines=[routine],
            _agno_run_context=context(),
        )
    assert (await _call(db, "get_products"))[1] == 1
    if os.db is not db:
        os.db.close()
