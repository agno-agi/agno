"""Task execution through real routes, run storage and a PostgreSQL durable queue."""

import asyncio
import json
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.job_queue import QueueConfig
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, CompanyConfig
from agno.os.job_queue import QueueWorker, resolve_queue_store
from agno.run.base import RunStatus
from agno.team import Team
from agno.workflow import Step, StepOutput, Workflow


class OfflineModel(Model):
    def __init__(self):
        super().__init__(id="offline", provider="test")

    def invoke(self, *args, **kwargs):
        return ModelResponse(
            role="assistant", content="Completed evidence-based draft", response_usage=MessageMetrics()
        )

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def draft(step_input):
    return StepOutput(content="Completed workflow draft")


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def system(request, tmp_path):
    schema = "execution_" + uuid4().hex
    queue_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    if "postgres" in request.param:
        cls = AsyncPostgresDb if request.param.startswith("async") else PostgresDb
        db = cls(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    else:
        cls = AsyncSqliteDb if request.param.startswith("async") else SqliteDb
        db = cls(db_file=str(tmp_path / "company.db"))
    agent = Agent(id="writer", model=OfflineModel(), db=db, telemetry=False)
    team = Team(id="editors", model=OfflineModel(), members=[], db=db, telemetry=False)
    workflow = Workflow(id="draft", steps=[Step(name="Draft", executor=draft)], db=db, telemetry=False)
    config = QueueConfig(durable=True, db=queue_db, max_attempts=2, retry_delay_seconds=0)
    os = AgentOS(
        db=db,
        agents=[agent],
        teams=[team],
        workflows=[workflow],
        company=CompanyConfig(),
        queue=config,
        telemetry=False,
    )
    app = os.get_app()
    components = {"writer": agent, "editors": team, "draft": workflow}
    worker = QueueWorker(
        resolve_queue_store(config, db), lambda kind, id, scope=None: components.get(id), config, authorization_app=app
    )
    worker._company_db = db
    app.state.queue_worker = worker
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, db, worker, os, components
    if isinstance(db, AsyncBaseDb):
        await db.close()
    else:
        db.close()
    with queue_db.db_engine.begin() as conn:
        conn.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
    queue_db.close()


async def accepted(client, kind="agent", id="writer"):
    product = (
        await client.post("/company/products", json={"name": "SDK", "metadata": {"secret": "never-forward"}})
    ).json()
    project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Release"})).json()
    task = (
        await client.post(
            "/company/tasks",
            json={
                "product_id": product["id"],
                "project_id": project["id"],
                "title": "Draft",
                "brief": "Write a draft",
                "evidence": [{"url": "https://example.com/evidence", "hash": "abc"}],
            },
        )
    ).json()
    response = await client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": kind, "executor_id": id},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def execute(worker):
    job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert job is not None
    await worker._execute_claimed(job)
    return await worker.store.get_job(job["id"])


@pytest.mark.asyncio
async def test_in_progress_requires_run_start(system):
    from agno.company.execution import _call

    client, db, worker, _, _ = system
    task = await accepted(client)
    path = f"/company/tasks/{task['id']}"
    for state in ("ready", "in_review"):
        before = await _call(db, "get_task", task["id"])
        assert before["status"] == state
        refused = await client.post(path + "/transitions", json={"target": "in_progress", "reason": "Start work"})
        assert refused.status_code == 409, refused.text
        assert "POST " + path + "/runs" in refused.json()["detail"]
        assert await _call(db, "get_task", task["id"]) == before
        if state == "ready":
            started = await client.post(path + "/runs")
            assert started.status_code == 202, started.text
            running = await _call(db, "get_task", task["id"])
            assert running["status"] == "in_progress"
            assert running["job_id"] == started.json()["run_id"]
            assert running["transitions"][-1]["attempt"] == 1
            assert (await execute(worker))["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,id", [("agent", "writer"), ("team", "editors"), ("workflow", "draft")])
async def test_execution_duplicate_context_history_and_attention(system, kind, id):
    client, db, worker, os, _ = system
    value = await accepted(client, kind, id)
    path = f"/company/tasks/{value['id']}"
    starts = await asyncio.gather(client.post(path + "/runs"), client.post(path + "/runs"))
    assert all(r.status_code == 202 for r in starts), [r.text for r in starts]
    assert starts[0].json()["run_id"] == starts[1].json()["run_id"]
    run_id = starts[0].json()["run_id"]
    job = await worker.store.get_job(run_id)
    payload = json.loads(job["payload"]["input"])
    assert set(payload) == {"brief", "wiki", "evidence", "execution_context"}
    assert payload["execution_context"]["stage"] == "accepted_task_execution"
    assert len(payload["wiki"]) == 4 and payload["evidence"][0]["hash"] == "abc"
    assert "never-forward" not in job["payload"]["input"]
    assert job["idempotency_key"] == f"company:{value['id']}:1" and job["max_attempts"] == 2
    assert (await execute(worker))["status"] == "completed"
    saved = (await client.get(path)).json()
    assert saved["status"] == "in_review" and "draft" in saved["result"]["content"]
    assert saved["session_id"] == value["session_id"]
    duplicate = await client.post(path + "/runs")
    assert duplicate.status_code == 409, duplicate.text
    history = (await client.get(path + "/runs", params={"limit": 1, "page": 1})).json()
    assert history["meta"]["total_count"] == 1
    assert (await client.get("/company/attention", params={"product_id": value["product_id"]})).json() == {
        "proposals": 0,
        "in_review": 1,
        "failed": 0,
    }
    assert (await client.post(path + "/runs", json={"attempt": 3})).status_code == 409
    assert (
        await client.post(path + "/transitions", json={"target": "in_progress", "reason": "Revise"})
    ).status_code == 409
    revisions = await asyncio.gather(
        client.post(path + "/runs", json={"attempt": 2}), client.post(path + "/runs", json={"attempt": 2})
    )
    assert all(response.status_code == 202 for response in revisions), [r.text for r in revisions]
    revision = revisions[0]
    assert revision.json()["run_id"] == revisions[1].json()["run_id"]
    assert revision.json()["session_id"] == value["session_id"] and revision.json()["run_id"] != run_id
    running = (await client.get(path)).json()
    assert running["status"] == "in_progress" and running["result"] is None
    assert (running["executor_type"], running["executor_id"]) == (kind, id)
    assert len([entry for entry in running["transitions"] if entry.get("attempt") == 2]) == 1
    assert running["transitions"][-1]["from"] == "in_review"
    assert running["transitions"][-1]["target"] == "in_progress"
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(path + "/runs", params={"limit": 1, "page": 2})).json()["meta"]["total_count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("first_failed", [False, True])
async def test_reaccepted_ready_starts_next_attempt(system, monkeypatch, automatic, first_failed):
    from agno.company.execution import _call
    from agno.db.schemas.tasks import task_run_id

    client, db, worker, _, components = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    before = await _call(db, "get_task", value["id"])
    assert (await client.post(path + "/runs", json={"attempt": 2})).status_code == 409
    assert await _call(db, "get_task", value["id"]) == before
    first = await client.post(path + "/runs")
    assert first.status_code == 202, first.text
    original = components["writer"].arun
    if first_failed:

        async def fail(*args, **kwargs):
            raise RuntimeError("First attempt failed")

        monkeypatch.setattr(components["writer"], "arun", fail)
        assert (await execute(worker))["status"] == "queued"
        assert (await execute(worker))["status"] == "failed"
        monkeypatch.setattr(components["writer"], "arun", original)
    else:
        assert (await execute(worker))["status"] == "completed"
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Rescope"})
    ).status_code == 200
    before = await _call(db, "get_task", value["id"])
    assert (await client.post(path + "/runs", json={"attempt": 2})).status_code == 409
    assert await _call(db, "get_task", value["id"]) == before
    assert await worker.store.get_job(task_run_id(value["id"], 2)) is None
    assert (await client.patch(path, json={"brief": "Revised scope"})).status_code == 200
    ready = await client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Accept revised scope", "executor_type": "agent", "executor_id": "writer"},
    )
    assert ready.status_code == 200, ready.text
    assert (await client.post(path + "/runs", json={"attempt": 1})).status_code == 409
    if automatic:
        executor, _ = await automation(system)
        result = await tick(executor, db)
        assert result["status"] == "success", result
    else:
        result = await client.post(path + "/runs", json={"attempt": 2})
        assert result.status_code == 202, result.text
    running = (await client.get(path)).json()
    assert running["status"] == "in_progress" and running["result"] is None
    assert running["session_id"] == first.json()["session_id"]
    assert running["job_id"] == task_run_id(value["id"], 2)
    assert running["transitions"][-1]["attempt"] == 2
    assert running["transitions"][-1]["from"] == "ready"
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(path)).json()["status"] == "in_review"


@pytest.mark.asyncio
async def test_cancellation_and_revocation(system):
    client, db, worker, os, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    response = await client.post(path + "/runs")
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    assert (await client.post(f"/company/runs/{run_id}/cancel")).status_code == 200
    assert (await worker.store.get_job(run_id))["status"] == "cancelled"
    next_run = await client.post(path + "/runs", json={"attempt": 2})
    assert next_run.status_code == 202, next_run.text
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Withdraw"})
    ).status_code == 200
    assert (await execute(worker))["status"] == "failed"
    assert (await client.get(path)).json()["status"] == "backlog"


@pytest.mark.asyncio
async def test_registry_recheck_and_retired_executor(system):
    client, db, worker, os, _ = system
    value = await accepted(client)
    os.registry.agents.clear()
    assert (await client.post(f"/company/tasks/{value['id']}/runs")).status_code == 409
    response = await client.post(
        f"/company/tasks/{value['id']}/transitions",
        json={"target": "ready", "reason": "Accept", "executor_type": "engineering", "executor_id": "codex"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bounded_failure_visible_without_changing_lifecycle(system, monkeypatch):
    client, db, worker, os, components = system
    value = await accepted(client)

    async def fail(*args, **kwargs):
        raise RuntimeError("executor failed")

    monkeypatch.setattr(components["writer"], "arun", fail)
    path = f"/company/tasks/{value['id']}"
    assert (await client.post(path + "/runs")).status_code == 202
    first = await execute(worker)
    assert first["status"] == "queued"
    pending = (await client.get(path)).json()
    assert pending["status"] == "in_progress" and pending["result"] is None
    assert (await client.get("/company/attention")).json()["failed"] == 0
    assert (await client.get("/company/tasks", params={"failed": "true"})).json()["meta"]["total_count"] == 0
    second = await execute(worker)
    assert second["status"] == "failed" and second["attempt"] == 2
    saved = (await client.get(path)).json()
    assert saved["status"] == "in_progress" and saved["result"]["status"] == "ERROR"
    assert (await client.get("/company/attention")).json()["failed"] == 1
    rows = (await client.get("/company/tasks", params={"failed": "true"})).json()
    assert rows["meta"]["total_count"] == 1 and rows["data"][0]["id"] == value["id"]


@pytest.mark.asyncio
async def test_queue_reconciliation_projects_completion_after_restart(system, monkeypatch):
    client, db, worker, os, components = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    assert (await client.post(path + "/runs")).status_code == 202

    async def lost_settlement(*args, **kwargs):
        return False

    monkeypatch.setattr(worker, "_asettle_ticket", lost_settlement)
    first = await execute(worker)
    assert first["status"] == "running"
    assert (await client.get(path)).json()["status"] == "in_progress"
    # Reclaim by a new worker after a lost lease; it must honor the terminal run row.
    restarted = QueueWorker(
        worker.store, worker.resolve_component, worker.config, authorization_app=worker.authorization_app
    )
    restarted._company_db = db
    queue_db = worker.config.db
    table = queue_db._get_table("jobs")
    with queue_db.Session() as session, session.begin():
        session.execute(table.update().where(table.c.id == first["id"]).values(locked_at=0))
    assert (await execute(restarted))["status"] == "completed"
    assert (await client.get(path)).json()["status"] == "in_review"
    assert (await client.get(path + "/runs")).json()["meta"]["total_count"] == 1


@pytest.mark.asyncio
async def test_custom_task_table_is_created_with_execution_fields(system):
    from sqlalchemy import inspect

    from agno.company.execution import _call

    client, db, worker, os, _ = system
    name = "custom_company_tasks"
    db.tasks_table_name = name
    value = await accepted(client)
    saved = await _call(db, "get_task", value["id"])
    assert saved["session_id"]
    assert saved["job_id"] is None and saved["result"] is None
    assert saved["evidence"] == [{"url": "https://example.com/evidence", "hash": "abc"}]

    def inspect_table(conn):
        inspector = inspect(conn)
        schema = getattr(db, "db_schema", None)
        return inspector.get_columns(name, schema=schema), inspector.get_indexes(name, schema=schema)

    if isinstance(db, AsyncBaseDb):
        async with db.db_engine.connect() as conn:
            columns, indexes = await conn.run_sync(inspect_table)
    else:
        with db.db_engine.connect() as conn:
            columns, indexes = inspect_table(conn)
    assert {"session_id", "job_id", "evidence", "result", "origin", "routine_id", "dedupe_key"} <= {
        column["name"] for column in columns
    }
    assert {f"idx_{name}_session_id", f"idx_{name}_job_id"} <= {index["name"] for index in indexes}

    response = await client.post(f"/company/tasks/{value['id']}/runs")
    assert response.status_code == 202, response.text
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(f"/company/tasks/{value['id']}")).json()["status"] == "in_review"


@pytest.mark.asyncio
async def test_results_cannot_cross_revoked_acceptance(system):
    from agno.company.execution import _call
    from agno.db.schemas.tasks import task_run_id

    client, db, worker, os, _ = system
    value = await accepted(client)
    reserved = await _call(
        db, "start_task_run", value["id"], 1, (await _call(db, "get_task", value["id"]))["transitions"]
    )
    await _call(db, "transition_task", value["id"], "backlog", "Withdraw")
    await _call(db, "transition_task", value["id"], "ready", "New scope", executor_type="agent", executor_id="writer")
    await _call(db, "transition_task", value["id"], "in_progress", "Manual work")
    assert (
        await _call(
            db,
            "complete_task_run",
            value["id"],
            task_run_id(value["id"], 1),
            {"status": "COMPLETED", "content": "stale"},
            expected_transitions=reserved["transitions"],
        )
        is None
    )
    saved = await _call(db, "get_task", value["id"])
    assert saved["status"] == "in_progress" and saved["result"] is None


@pytest.mark.asyncio
async def test_run_history_and_revision_survive_ticket_retention(system):
    client, db, worker, os, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    response = await client.post(path + "/runs")
    run_id = response.json()["run_id"]
    assert (await execute(worker))["status"] == "completed"
    table = worker.config.db._get_table("jobs")
    with worker.config.db.Session() as session, session.begin():
        session.execute(table.delete().where(table.c.id == run_id))
    assert (await client.post(path + "/runs")).status_code == 409
    response = await client.get(f"/company/runs/{run_id}")
    assert response.status_code == 200 and response.json()["status"] == "COMPLETED", response.text
    assert (
        await client.post(path + "/transitions", json={"target": "in_progress", "reason": "Revise draft"})
    ).status_code == 409
    revision = await client.post(path + "/runs", json={"attempt": 2})
    assert revision.status_code == 202, revision.text
    assert revision.json()["run_id"] != run_id
    os.registry.agents.clear()
    assert (await client.get(path + "/runs")).json()["meta"]["total_count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "missing", "markdown", "website", "git", "plain_proposal"])
async def test_routine_intake_through_scheduler_and_durable_queue(system, tmp_path, monkeypatch, failure):
    from agno.company.execution import _call
    from agno.scheduler.executor import ScheduleExecutor
    from agno.tools.company import CompanyTools

    client, db, worker, os, components = system
    path = tmp_path / "release.md"
    path.write_text("A released capability")
    product = (await client.post("/company/products", json={"name": "Docs"})).json()
    project = (
        await client.post("/company/projects", json={"product_id": product["id"], "name": "Documentation"})
    ).json()
    source = (
        await client.post(
            "/company/sources", json={"product_id": product["id"], "type": "markdown", "reference": str(path)}
        )
    ).json()

    if failure == "missing":
        path.unlink()
    elif failure == "markdown":

        def broken_reader(*args, **kwargs):
            raise OSError("Reader backend failed")

        monkeypatch.setattr("agno.knowledge.reader.markdown_reader.MarkdownReader.read", broken_reader)
    elif failure == "git":
        (tmp_path / ".env").write_text("Excluded from the Source")
        await _call(db, "update_source", source["id"], type="git", reference=str(tmp_path), config={"paths": [".env"]})
    elif failure == "website":
        await _call(db, "update_source", source["id"], type="website", reference="https://docs.example.test")
        monkeypatch.setattr("agno.knowledge.reader.website_reader.WebsiteReader.read", lambda *args, **kwargs: [])
    tool_name = "read_product_source" if failure in {"markdown", "website"} else "intake_product_source"
    arguments = {"source_id": source["id"]}
    if failure == "plain_proposal":
        tool_name = "propose_company_task"
        arguments = {"product_id": product["id"], "project_id": project["id"], "title": "Undeduplicated proposal"}
    if tool_name == "read_product_source":
        arguments["path"] = "https://docs.example.test" if failure == "website" else path.name
    if tool_name == "intake_product_source":
        arguments.update(
            project_id=project["id"],
            title="Document release",
            brief="Explain the capability",
            proposal_key="release-docs",
            evidence_links=[path.as_uri()],
            evidence_hashes={path.as_uri(): "unavailable"},
        )

    if failure is None:
        from agno.company.sources import read_source

        evidence = read_source(source, "observed")
        arguments["evidence_hashes"] = {item["link"]: item["content_hash"] for item in evidence}

    class IntakeModel(OfflineModel):
        def invoke(self, messages, *args, **kwargs):
            assert any(product["id"] in str(message.content) for message in messages if message.role == "user")
            if not any(message.role == "tool" for message in messages):
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": "intake",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                    response_usage=MessageMetrics(),
                )
            return ModelResponse(
                role="assistant",
                content="Source checked; proposals remain in Backlog.",
                response_usage=MessageMetrics(),
            )

    components["writer"].model = IntakeModel()
    components["writer"].tools = [CompanyTools(db)]
    os.resync(worker.authorization_app)
    response = await client.post(
        "/company/routines",
        json={
            "product_id": product["id"],
            "name": "intake",
            "template": "intake",
            "executor_type": "agent",
            "executor_id": "writer",
            "cron_expr": "0 * * * *",
        },
    )
    assert response.status_code == 201, response.text
    routine = response.json()
    app = worker.authorization_app
    app.state.internal_service_token = "heartbeat-internal"
    executor = ScheduleExecutor(base_url="http://test", internal_service_token="heartbeat-internal", poll_interval=0)
    original_request = client.request

    async def request_and_work(method, url, **kwargs):
        result = await original_request(method, url, **kwargs)
        if method == "POST" and result.status_code == 202:
            completed = await execute(worker)
            if failure and completed["status"] == "queued":
                completed = await execute(worker)
            assert completed["status"] == ("failed" if failure else "completed"), completed
        return result

    from unittest.mock import AsyncMock

    executor._get_client = AsyncMock(return_value=SimpleClient(request_and_work))
    schedule = await _call(db, "get_schedule", routine["id"])
    first = await executor.execute(schedule, db, release_schedule=False)
    if failure:
        assert first["status"] == "failed", first
        assert tool_name in first["error"]
        assert (await _call(db, "get_tasks", product_id=product["id"]))[1] == 0
        history = (await client.get("/company/routines/" + routine["id"] + "/runs")).json()
        assert history["data"][0]["status"] == "failed"
        assert (await client.get("/company/attention", params={"product_id": product["id"]})).json()["failed"] == 1
        run = await components["writer"].aget_run_output(first["run_id"], first["session_id"])
        assert run.status == RunStatus.error
        return
    assert first["status"] == "success", first
    rows, total = await _call(db, "get_tasks", product_id=product["id"])
    assert total == 1, first
    assert rows[0]["routine_id"] == routine["id"]
    task_response = (await client.get("/company/tasks/" + rows[0]["id"])).json()
    assert task_response["origin"] == "routine"
    assert task_response["routine_id"] == routine["id"]
    assert task_response["dedupe_key"] == rows[0]["dedupe_key"]
    assert rows[0]["evidence"][0]["run_id"] == first["run_id"]
    assert rows[0]["status"] == "backlog"
    second = await executor.execute(schedule, db, release_schedule=False)
    assert second["status"] == "success", second
    assert (await _call(db, "get_tasks", product_id=product["id"]))[1] == 1
    history = (await client.get("/company/routines/" + routine["id"] + "/runs")).json()
    assert history["meta"]["total_count"] == 2
    assert all(run["status"] == "success" for run in history["data"])


class SimpleClient:
    def __init__(self, request):
        self.request = request


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,id", [("agent", "writer"), ("team", "editors"), ("workflow", "draft")])
async def test_invalid_executor_input_does_not_reserve_attempt(system, kind, id):
    from pydantic import BaseModel

    from agno.db.schemas.tasks import task_run_id

    class TopicInput(BaseModel):
        topic: str

    client, db, worker, os, components = system
    component = components[id]
    component.input_schema = TopicInput
    value = await accepted(client, kind, id)
    path = f"/company/tasks/{value['id']}"
    response = await client.post(path + "/runs")
    assert response.status_code == 400, response.text
    saved = (await client.get(path)).json()
    assert saved["status"] == "ready"
    assert saved["job_id"] is None
    assert saved["transitions"] == value["transitions"]
    assert await worker.store.get_job(task_run_id(value["id"], 1)) is None
    assert (await client.get(path + "/runs")).json()["meta"]["total_count"] == 0

    # A rejected input has not consumed the attempt. Correcting the executor's
    # schema permits the same first attempt to enter the ordinary durable route.
    component.input_schema = None
    retried = await client.post(path + "/runs")
    assert retried.status_code == 202, retried.text
    assert (await execute(worker))["status"] == "completed"


@pytest.mark.asyncio
async def test_nonfailed_filter_includes_sql_and_json_null_results(system):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    unstarted = await accepted(client)
    pending = await accepted(client)
    response = await client.post(f"/company/tasks/{pending['id']}/runs")
    assert response.status_code == 202, response.text
    nonfailed = (await client.get("/company/tasks", params={"failed": "false", "limit": 1})).json()
    assert nonfailed["meta"]["total_count"] == 2
    assert len(nonfailed["data"]) == 1
    assert (await client.get("/company/tasks", params={"failed": "true"})).json()["meta"]["total_count"] == 0

    await _call(
        db, "complete_task_run", pending["id"], response.json()["run_id"], {"status": "ERROR", "content": "Failure"}
    )
    nonfailed = (await client.get("/company/tasks", params={"failed": "false"})).json()
    failed = (await client.get("/company/tasks", params={"failed": "true"})).json()
    assert nonfailed["meta"]["total_count"] == 1
    assert [row["id"] for row in nonfailed["data"]] == [unstarted["id"]]
    assert failed["meta"]["total_count"] == 1
    assert [row["id"] for row in failed["data"]] == [pending["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["cancelled", "backlog", "ready", "in_review", "done"])
@pytest.mark.parametrize("result_status", ["ERROR", "CANCELLED"])
async def test_attention_clears_acted_on_failures_and_preserves_results(system, target, result_status):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    value = await accepted(client)
    other = await accepted(client)
    for task in (value, other):
        reserved = await _call(
            db, "start_task_run", task["id"], 1, (await _call(db, "get_task", task["id"]))["transitions"]
        )
        await _call(
            db, "complete_task_run", task["id"], reserved["job_id"], {"status": result_status, "content": "Failure"}
        )
    path = f"/company/tasks/{value['id']}"
    product_filter = {"product_id": value["product_id"]}
    assert (await client.get("/company/attention", params=product_filter)).json()["failed"] == 1
    assert (await client.get("/company/attention")).json()["failed"] == 2
    steps = ["backlog", "ready"] if target == "ready" else ["in_review", "done"] if target == "done" else [target]
    for step in steps:
        body = {"target": step, "reason": "Human acted on failure"}
        if step == "ready":
            body.update(executor_type="agent", executor_id="writer")
        response = await client.post(path + "/transitions", json=body)
        assert response.status_code == 200, response.text
        attention = (await client.get("/company/attention", params=product_filter)).json()
        assert attention == {"proposals": int(step == "backlog"), "in_review": int(step == "in_review"), "failed": 0}
    assert (await client.get(path)).json()["result"] == {"status": result_status, "content": "Failure"}
    assert (await client.get("/company/attention")).json()["failed"] == 1
    failed = (await client.get("/company/tasks", params={"failed": "true", "limit": 1})).json()
    nonfailed = (await client.get("/company/tasks", params={"failed": "false", "limit": 1})).json()
    assert failed["meta"]["total_count"] == nonfailed["meta"]["total_count"] == 1
    assert [row["id"] for row in failed["data"]] == [other["id"]]
    assert [row["id"] for row in nonfailed["data"]] == [value["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,executor_id",
    [
        ("agent", "company-manager-internal"),
        ("agent", "product-manager-internal"),
        ("team", "os-manager-internal"),
        ("agent", "platform-builder-internal"),
        ("agent", "platform-manager-internal"),
    ],
)
@pytest.mark.parametrize("phase", ["acceptance", "start"])
async def test_all_framework_executor_ids_are_rejected(system, monkeypatch, kind, executor_id, phase):
    from unittest.mock import Mock

    from agno.company.execution import _call

    client, db, worker, os, components = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    await _call(db, "transition_task", value["id"], "backlog", "Replan")
    # The Company boundary must reject reserved IDs even if a custom registry
    # resolver returns a component, rather than relying on catalog exclusion.
    resolve = Mock(return_value=components["writer" if kind == "agent" else "editors"])
    monkeypatch.setattr(os.registry, "get_" + kind, resolve)
    if phase == "acceptance":
        response = await client.post(
            path + "/transitions",
            json={"target": "ready", "reason": "Accept", "executor_type": kind, "executor_id": executor_id},
        )
        assert response.status_code == 409, response.text
        assert (await client.get(path)).json()["status"] == "backlog"
    else:
        await _call(
            db,
            "transition_task",
            value["id"],
            "ready",
            "Previously accepted",
            executor_type=kind,
            executor_id=executor_id,
        )
        response = await client.post(path + "/runs")
        assert response.status_code == 409, response.text
        assert (await client.get(path)).json()["job_id"] is None
    resolve.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,id", [("agent", "writer"), ("team", "editors"), ("workflow", "draft")])
@pytest.mark.parametrize("attempt,previous_status", [(1, None), (2, "ERROR"), (2, "COMPLETED")])
async def test_full_queue_leaves_task_and_attempt_unchanged(system, kind, id, attempt, previous_status):
    from agno.company.execution import _call
    from agno.db.schemas.tasks import task_run_id

    client, db, worker, os, _ = system
    value = await accepted(client, kind, id)
    path = f"/company/tasks/{value['id']}"
    if attempt == 2:
        response = await client.post(path + "/runs")
        if previous_status == "COMPLETED":
            assert (await execute(worker))["status"] == "completed"
        else:
            job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
            assert job["id"] == response.json()["run_id"]
            await _call(
                db, "complete_task_run", value["id"], job["id"], {"status": "ERROR", "content": "Previous failure"}
            )
            assert await worker.store.complete_job(job["id"], worker.worker_id, job["attempt"], "failed")
    filler = await accepted(client)
    filler_run = await client.post(f"/company/tasks/{filler['id']}/runs")
    worker.config.max_queue_depth = 1
    before = (await client.get(path)).json()
    attention = (await client.get("/company/attention")).json()
    for _ in range(2):
        response = await client.post(path + "/runs", json={"attempt": attempt})
        assert response.status_code == 429, response.text
        assert (await client.get(path)).json() == before
        assert await worker.store.get_job(task_run_id(value["id"], attempt)) is None
        assert (await client.get(path + "/runs")).json()["meta"]["total_count"] == attempt - 1
        assert (await client.get("/company/attention")).json() == attention
    assert (await client.post(f"/company/runs/{filler_run.json()['run_id']}/cancel")).status_code == 200
    retried = await client.post(path + "/runs", json={"attempt": attempt})
    assert retried.status_code == 202, retried.text
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(path)).json()["status"] == "in_review"


@pytest.mark.asyncio
async def test_rejected_duplicate_cannot_undo_accepted_submission(system, monkeypatch):
    client, db, worker, os, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    filler = await accepted(client)
    filler_run = await client.post(f"/company/tasks/{filler['id']}/runs")
    worker.config.max_queue_depth = 1
    enqueue = worker.store.enqueue_job
    rejected = asyncio.Event()
    release = asyncio.Event()

    async def delayed_rejection(*args, **kwargs):
        result = await enqueue(*args, **kwargs)
        if result["reason"] == "queue_full":
            rejected.set()
            await release.wait()
        return result

    monkeypatch.setattr(worker.store, "enqueue_job", delayed_rejection)
    first = asyncio.create_task(client.post(path + "/runs"))
    try:
        await asyncio.wait_for(rejected.wait(), timeout=10)
        assert (await client.post(f"/company/runs/{filler_run.json()['run_id']}/cancel")).status_code == 200
        second = await client.post(path + "/runs")
        assert second.status_code == 202, second.text
    finally:
        release.set()
    assert (await first).status_code == 429
    saved = (await client.get(path)).json()
    assert saved["status"] == "in_progress" and saved["job_id"] == second.json()["run_id"]
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(path)).json()["status"] == "in_review"


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery", ["worker", "duplicate", "cancel", "revoke", "archive_restore"])
async def test_worker_recovers_task_projection_after_committed_enqueue(system, monkeypatch, recovery):
    import agno.company.execution as execution
    from agno.db.schemas.tasks import task_run_id

    client, db, worker, os, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    reserve = execution._reserve_task

    async def lost_submitter(*args, **kwargs):
        raise RuntimeError("Submitter stopped after enqueue")

    monkeypatch.setattr(execution, "_reserve_task", lost_submitter)
    with pytest.raises(RuntimeError, match="Submitter stopped after enqueue"):
        await client.post(path + "/runs")
    assert (await client.get(path)).json() == value
    assert await worker.store.get_job(task_run_id(value["id"], 1)) is not None
    monkeypatch.setattr(execution, "_reserve_task", reserve)
    if recovery == "duplicate":
        assert (await client.post(path + "/runs")).status_code == 202
        assert (await client.get(path)).json()["status"] == "in_progress"
    elif recovery == "cancel":
        run_id = task_run_id(value["id"], 1)
        assert (await client.post(f"/company/runs/{run_id}/cancel")).status_code == 200
        assert (await client.post(path + "/runs", json={"attempt": 2})).status_code == 202
    elif recovery == "revoke":
        assert (
            await client.post(path + "/transitions", json={"target": "backlog", "reason": "Withdraw"})
        ).status_code == 200
    elif recovery == "archive_restore":
        assert (await client.delete(path)).status_code == 204
        restored = await client.post(path + "/restore")
        assert restored.status_code == 200, restored.text
        assert restored.json()["transitions"] == value["transitions"]
    result = await execute(worker)
    saved = (await client.get(path)).json()
    assert result["status"] == ("failed" if recovery == "revoke" else "completed")
    assert saved["status"] == ("backlog" if recovery == "revoke" else "in_review")
    if recovery == "revoke":
        assert saved["job_id"] is None and saved["result"] is None
    else:
        assert saved["result"]["status"] == "COMPLETED"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,id", [("agent", "writer"), ("team", "editors"), ("workflow", "draft")])
async def test_cancelled_task_is_visible_and_can_start_another_attempt(system, kind, id):
    from agno.company.execution import _project_run

    client, db, worker, os, _ = system
    value = await accepted(client, kind, id)
    path = f"/company/tasks/{value['id']}"
    response = await client.post(path + "/runs")
    run_id = response.json()["run_id"]
    job = await worker.store.get_job(run_id)
    assert (await client.post(f"/company/runs/{run_id}/cancel")).status_code == 200
    assert (await worker.store.get_job(run_id))["status"] == "cancelled"
    saved = (await client.get(path)).json()
    assert saved["status"] == "in_progress"
    assert saved["result"]["status"] == "CANCELLED" and saved["result"]["run_id"] == run_id
    assert saved["result"]["content"]
    assert (await client.get("/company/attention", params={"product_id": value["product_id"]})).json()["failed"] == 1
    assert (await client.get("/company/tasks", params={"failed": True})).json()["meta"]["total_count"] == 1
    assert (await client.get("/company/tasks", params={"failed": False})).json()["meta"]["total_count"] == 0
    assert (await client.get(path + "/runs")).json()["data"][0]["status"] == "CANCELLED"

    response = await client.post(path + "/runs", json={"attempt": 2})
    assert response.status_code == 202, response.text
    pending = (await client.get(path)).json()
    assert pending["session_id"] == value["session_id"] and pending["result"] is None
    await _project_run(worker, job, "cancelled")
    assert (await client.get(path)).json() == pending
    assert (await client.get("/company/attention")).json()["failed"] == 0
    assert (await execute(worker))["status"] == "completed"


@pytest.mark.asyncio
async def test_cancellation_during_execution_projects_task_result(system, monkeypatch):
    from agno.exceptions import RunCancelledException

    client, db, worker, os, components = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    response = await client.post(path + "/runs")
    run_id = response.json()["run_id"]
    started = asyncio.Event()
    release = asyncio.Event()

    async def cancelled_run(*args, **kwargs):
        started.set()
        await release.wait()
        raise RunCancelledException("User cancelled execution")

    monkeypatch.setattr(components["writer"], "arun", cancelled_run)
    running = asyncio.create_task(execute(worker))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        assert (await client.post(f"/company/runs/{run_id}/cancel")).status_code == 200
    finally:
        release.set()
    assert (await running)["status"] == "cancelled"
    saved = (await client.get(path)).json()
    assert saved["status"] == "in_progress" and saved["result"]["status"] == "CANCELLED"
    assert (await client.get("/company/attention")).json()["failed"] == 1
    assert (await client.post(path + "/transitions", json={"target": "backlog", "reason": "Replan"})).status_code == 200
    assert (await client.get("/company/attention")).json() == {"proposals": 1, "in_review": 0, "failed": 0}
    assert (await client.get(path)).json()["result"]["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_projection_failure_is_recovered_by_queue(system, monkeypatch):
    import agno.company.execution as execution

    client, db, worker, os, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    response = await client.post(path + "/runs")
    run_id = response.json()["run_id"]
    project = execution._project_run

    async def interrupted(*args, **kwargs):
        raise RuntimeError("Task projection interrupted")

    monkeypatch.setattr(execution, "_project_run", interrupted)
    # The CANCELLED run row is written, so the cancel succeeds and its claim settles the ticket.
    assert (await client.post(f"/company/runs/{run_id}/cancel")).status_code == 200
    assert (await worker.store.get_job(run_id))["status"] == "queued"
    assert (await client.get(path)).json()["result"] is None
    monkeypatch.setattr(execution, "_project_run", project)
    assert (await execute(worker))["status"] == "cancelled"
    assert (await client.get(path)).json()["result"]["status"] == "CANCELLED"
    assert (await client.get("/company/attention")).json()["failed"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("claimed", [False, True], ids=["queued", "claimed"])
async def test_changed_acceptance_during_enqueue_returns_conflict(system, monkeypatch, claimed):
    from agno.db.schemas.tasks import task_run_id

    client, db, worker, os, components = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    enqueue = worker.store.enqueue_job
    claimed_job = None

    async def revoke_before_enqueue(*args, **kwargs):
        nonlocal claimed_job
        revoked = await client.post(path + "/transitions", json={"target": "backlog", "reason": "Scope changed"})
        assert revoked.status_code == 200
        result = await enqueue(*args, **kwargs)
        if claimed:
            claimed_job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
        return result

    monkeypatch.setattr(worker.store, "enqueue_job", revoke_before_enqueue)
    response = await client.post(path + "/runs")
    assert response.status_code == 409, response.text
    assert "acceptance" in response.json()["detail"]
    saved = (await client.get(path)).json()
    assert saved["status"] == "backlog" and saved["job_id"] is None and saved["result"] is None
    run_id = task_run_id(value["id"], 1)
    if claimed:
        from unittest.mock import AsyncMock

        run = AsyncMock(side_effect=AssertionError("Revoked work must never execute"))
        monkeypatch.setattr(components["writer"], "arun", run)
        await worker._execute_claimed(claimed_job)
        run.assert_not_awaited()
    job = await worker.store.get_job(run_id)
    assert job["status"] == ("failed" if claimed else "cancelled")
    assert (await client.get(path)).json() == saved
    assert (await client.get("/company/attention")).json() == {"proposals": 1, "in_review": 0, "failed": 0}


@pytest.mark.asyncio
async def test_worker_completion_before_submitter_reservation_still_returns_accepted(system, monkeypatch):
    client, db, worker, os, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    enqueue = worker.store.enqueue_job

    async def complete_before_submitter_returns(*args, **kwargs):
        result = await enqueue(*args, **kwargs)
        assert (await execute(worker))["status"] == "completed"
        return result

    monkeypatch.setattr(worker.store, "enqueue_job", complete_before_submitter_returns)
    response = await client.post(path + "/runs")
    assert response.status_code == 202, response.text
    saved = (await client.get(path)).json()
    assert saved["status"] == "in_review" and saved["result"]["status"] == "COMPLETED"
    assert (await worker.store.get_job(response.json()["run_id"]))["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "running", "revoked"])
async def test_task_archive_restore_preserves_queued_acceptance(system, monkeypatch, phase):
    client, db, worker, os, components = system
    task = await accepted(client)
    path = "/company/tasks/" + task["id"]
    started = await client.post(path + "/runs")
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    before = (await client.get(path)).json()
    entered, release = asyncio.Event(), asyncio.Event()
    original = components["writer"].arun

    async def paused(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    running = None
    if phase == "running":
        monkeypatch.setattr(components["writer"], "arun", paused)
        running = asyncio.create_task(execute(worker))
    try:
        if running is not None:
            await asyncio.wait_for(entered.wait(), timeout=10)
        assert (await client.delete(path)).status_code == 204
        restored = await client.post(path + "/restore")
        assert restored.status_code == 200, restored.text
        for key in ["transitions", "session_id", "job_id", "evidence", "result", "accepted_at", "accepted_by"]:
            assert restored.json()[key] == before[key]
        if phase == "revoked":
            response = await client.post(path + "/transitions", json={"target": "backlog", "reason": "Withdraw"})
            assert response.status_code == 200, response.text
    finally:
        release.set()
    result = await asyncio.wait_for(running if running is not None else execute(worker), timeout=30)
    saved = (await client.get(path)).json()
    if phase == "revoked":
        assert result["status"] == "failed"
        assert saved["status"] == "backlog" and saved["result"] is None
    else:
        assert result["status"] == "completed"
        assert saved["status"] == "in_review" and saved["result"]["status"] == "COMPLETED"
        assert saved["result"]["run_id"] == run_id
        assert (await client.get("/company/attention")).json()["in_review"] == 1


async def automation(system):
    from agno.company.routines import _CompanyScheduleExecutor, _ensure_automation_schedule

    client, db, worker, os, _ = system
    worker._company_schedule_db = db
    executor = _CompanyScheduleExecutor(
        os, worker.authorization_app, base_url="http://test", internal_service_token="test"
    )
    schedule = await _ensure_automation_schedule(db)
    return executor, schedule


async def tick(executor, db):
    from agno.company.execution import _call

    claimed = await _call(db, "claim_due_schedule", str(uuid4()))
    if claimed is None:
        return None
    return await executor.execute(claimed, db)


@pytest.mark.asyncio
async def test_automation_concurrent_ticks_and_restart(system, monkeypatch):
    from agno.company.execution import _call
    from agno.company.routines import _CompanyScheduleExecutor

    client, db, worker, os, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    results = await asyncio.gather(tick(executor, db), tick(executor, db))
    assert sum(result is not None for result in results) == 1
    result = next(result for result in results if result)
    assert result["status"] == "success", result
    saved = await _call(db, "get_task", task["id"])
    assert saved["job_id"] is not None, result
    run_id = saved["job_id"]
    assert (await worker.store.get_job(run_id))["idempotency_key"] == f"company:{task['id']}:1"
    # A new scheduler after submission sees the same durable Task reservation.
    restarted = _CompanyScheduleExecutor(
        os, worker.authorization_app, base_url="http://test", internal_service_token="test"
    )
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    await tick(restarted, db)
    assert (await _call(db, "get_task", task["id"]))["job_id"] == run_id
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(f"/company/tasks/{task['id']}/runs")).json()["meta"]["total_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
async def test_automation_crash_during_dispatch(system, monkeypatch, queued):
    from agno.company.execution import _call
    from agno.os.routers.company import runs

    client, db, worker, os, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    original = runs._run_route

    async def interrupted(*args, **kwargs):
        if queued:
            await original(*args, **kwargs)
        raise RuntimeError("process stopped before dispatch response")

    monkeypatch.setattr(runs, "_run_route", interrupted)
    first = await tick(executor, db)
    reserved = await _call(db, "get_task", task["id"])
    from agno.db.schemas.tasks import task_run_id

    run_id = task_run_id(task["id"], 1)
    # The existing run route commits the queue ticket before projecting the Task.
    # A pre-submit interruption leaves Ready work; a lost reply retains the attempt.
    assert reserved["status"] == ("in_progress" if queued else "ready"), first
    assert reserved["job_id"] == (run_id if queued else None)
    assert (await worker.store.get_job(run_id) is not None) is queued
    monkeypatch.setattr(runs, "_run_route", original)
    restarted, _ = await automation(system)
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    second = await tick(restarted, db)
    assert await worker.store.get_job(run_id) is not None, second
    assert (await _call(db, "get_task", task["id"]))["job_id"] == run_id
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(f"/company/tasks/{task['id']}/runs")).json()["meta"]["total_count"] == 1


@pytest.mark.asyncio
async def test_automation_backlog_after_queue_never_executes(system):
    client, db, worker, os, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    result = await tick(executor, db)
    path = f"/company/tasks/{task['id']}"
    assert (await client.get(path)).json()["status"] == "in_progress", result
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Withdraw"})
    ).status_code == 200
    assert (await execute(worker))["status"] == "failed"
    assert (await client.get(path)).json()["status"] == "backlog"
    assert "draft" not in json.dumps((await client.get(path)).json().get("result"))


async def intake_proposal(manager, title, evidence, **kwargs):
    from agno.company.routines import _manager_call

    return await _manager_call(
        manager,
        "intake",
        source_id=evidence[0]["source_id"],
        run_id="proposal-run",
        proposal=dict(
            title=title,
            brief=kwargs.pop("brief", title),
            proposal_key=title,
            evidence_links=[item["link"] for item in evidence],
            evidence_hashes={item["link"]: item["content_hash"] for item in evidence},
        ),
        **kwargs,
    )


async def routine_proposal(system, tmp_path, *, policy=None, executor_id="writer", template="intake"):
    from agno.company.manager import AsyncCompanyManager, CompanyManager
    from agno.company.routines import _manager_call, _RoutineAuthorization
    from agno.run.authorization import authorization_scope

    client, db, worker, os, _ = system
    product = (await client.post("/company/products", json={"name": "Docs"})).json()
    project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Release"})).json()
    assert (
        await client.post(
            f"/company/projects/{project['id']}/transitions", json={"target": "active", "reason": "Start"}
        )
    ).status_code == 200
    source_path = tmp_path / (product["id"] + ".md")
    source_path.write_text("# Release\nVerified Source material.\n")
    source = (
        await client.post(
            "/company/sources", json={"product_id": product["id"], "type": "markdown", "reference": str(source_path)}
        )
    ).json()
    if policy is None:
        policy = {
            "executor_type": "agent",
            "executor_id": "writer",
            "source_ids": [source["id"]],
            "work_scope": {"product_ids": [product["id"]], "project_ids": [project["id"]]},
            "required_checks": ["project_active", "has_source_evidence", "executor_registered"],
            "limits": {"max_acceptances": 1, "expires_at": int(time.time()) + 3600},
        }
    response = await client.post(
        "/company/routines",
        json={
            "product_id": product["id"],
            "name": template or "custom",
            "template": template,
            **({"instructions": "Inspect work and propose follow-up."} if template is None else {}),
            "executor_type": "agent",
            "executor_id": "writer",
            "cron_expr": "0 0 * * *",
            "auto_accept": policy,
        },
    )
    assert response.status_code == 201, response.text
    routine = response.json()
    manager = AsyncCompanyManager(db, os.registry) if isinstance(db, AsyncBaseDb) else CompanyManager(db, os.registry)
    evidence = await _manager_call(manager, "read_source", source["id"], "source-run")
    evidence = [{key: value for key, value in item.items() if key != "content"} for item in evidence]
    with authorization_scope(lambda: _RoutineAuthorization(None, routine["id"])):
        task = await intake_proposal(
            manager,
            "Draft",
            brief="Write release notes",
            project_id=project["id"],
            executor_type="agent",
            executor_id=executor_id,
            evidence=evidence,
        )
    assert task["origin"] == "routine" and task["routine_id"] == routine["id"]
    return task, routine, manager


@pytest.mark.asyncio
async def test_builtin_checks_on_fresh_deployment_and_policy_limit(system, tmp_path):
    from agno.company.execution import _call
    from agno.company.routines import _RoutineAuthorization
    from agno.run.authorization import authorization_scope

    client, db, worker, os, _ = system
    assert os.company.acceptance_checks == {}
    task, routine, manager = await routine_proposal(system, tmp_path)
    executor, _ = await automation(system)
    with authorization_scope(lambda: _RoutineAuthorization(None, routine["id"])):
        other = await intake_proposal(
            manager,
            "Other",
            project_id=task["project_id"],
            executor_type="agent",
            executor_id="writer",
            evidence=task["evidence"],
        )
    results = await asyncio.gather(executor._accept(task), executor._accept(other), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1, results
    assert any("limit" in str(result) for result in results), results
    ready = next(result for result in results if isinstance(result, dict))
    assert ready["status"] == "ready"
    assert await executor._dispatch(ready)
    assert (await execute(worker))["status"] == "completed"
    # Soft deletion and a restart do not replenish the accepted-work budget.
    await _call(db, "transition_task", ready["id"], "cancelled", "Archive reviewed work")
    assert await _call(db, "delete_task", ready["id"])
    loser = other if ready["id"] == task["id"] else task
    with pytest.raises(ValueError, match="limit"):
        await executor._accept(loser)


@pytest.mark.asyncio
async def test_auto_accept_executor_mismatch_revocation_unknown_and_forged_evidence(system, tmp_path):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path, executor_id="agent-b")
    executor, _ = await automation(system)
    with pytest.raises(ValueError, match="executor"):
        await executor._accept(task)
    task = await _call(db, "update_task", task["id"], executor_id="writer")
    original = task["evidence"]
    task = await _call(db, "update_task", task["id"], evidence=[{**original[0], "content_hash": "agent-asserted"}])
    with pytest.raises(ValueError, match="has_source_evidence"):
        await executor._accept(task)
    task = await _call(db, "update_task", task["id"], evidence=original)
    # Direct scheduler edits must also fail closed at the acceptance boundary.
    row = await _call(db, "get_schedule", routine["id"])
    payload = row["payload"]
    payload["metadata"]["auto_accept"]["required_checks"] = ["not-installed"]
    await _call(db, "update_schedule", routine["id"], payload=payload)
    with pytest.raises(ValueError, match="Unknown"):
        await executor._accept(task)
    assert (await _call(db, "get_task", task["id"]))["status"] == "backlog"
    result = await tick(executor, db)
    skipped = next(item for item in result["output"]["tasks"] if item["task_id"] == task["id"])
    assert skipped["status"] == "skipped" and "Unknown" in skipped["reason"]
    assert (await client.patch(f"/company/routines/{routine['id']}", json={"auto_accept": False})).status_code == 200
    with pytest.raises(ValueError, match="no human"):
        await executor._accept(task)


@pytest.mark.asyncio
async def test_auto_accept_revocation_after_queue_and_scope_changes_during_check(system, tmp_path):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    executor, _ = await automation(system)
    ready = await executor._accept(task)
    await executor._dispatch(ready)
    assert (await client.patch(f"/company/routines/{routine['id']}", json={"auto_accept": False})).status_code == 200
    with pytest.raises(ValueError, match="revoked"):
        await executor._dispatch(ready)
    assert (await execute(worker))["status"] == "failed"
    assert (await _call(db, "get_task", task["id"]))["status"] != "in_review"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["proposal", "authorization", "expiry", "scope", "sources"])
async def test_auto_accept_rechecks_every_bound_and_check_races(system, tmp_path, change):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path)
    executor, _ = await automation(system)
    schedule = await _call(db, "get_schedule", routine["id"])
    policy = schedule["payload"]["metadata"]["auto_accept"]
    if change in {"proposal", "authorization"}:

        async def check(observed, manager):
            if change == "proposal":
                await _call(db, "update_task", observed["id"], brief="Changed during check")
            else:
                await _call(db, "update_schedule", routine["id"], enabled=False)
            return True

        os.company.acceptance_checks["race"] = check
        policy["required_checks"] = ["race"]
    elif change == "expiry":
        policy["limits"]["expires_at"] = 1
    elif change == "scope":
        policy["work_scope"]["project_ids"] = []
    else:
        policy["source_ids"] = []
    await _call(db, "update_schedule", routine["id"], payload=schedule["payload"])
    with pytest.raises(ValueError):
        await executor._accept(task)
    assert (await _call(db, "get_task", task["id"]))["status"] == "backlog"


@pytest.mark.asyncio
async def test_automation_records_revocation_before_dispatch(system, monkeypatch):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    value = await accepted(client)
    executor, schedule = await automation(system)
    original = executor._dispatch

    async def revoke(task):
        await _call(db, "transition_task", task["id"], "backlog", "Withdraw before dispatch")
        return await original(task)

    monkeypatch.setattr(executor, "_dispatch", revoke)
    result = await tick(executor, db)
    assert result["status"] == "failed"
    assert result["output"]["tasks"][0]["status"] == "failed"
    assert "changed" in result["output"]["tasks"][0]["reason"]
    assert (await _call(db, "get_task", value["id"]))["job_id"] is None


@pytest.mark.asyncio
async def test_routine_can_still_propose_projects(system):
    from agno.company.manager import AsyncCompanyManager, CompanyManager
    from agno.company.routines import _manager_call, _RoutineAuthorization
    from agno.run.authorization import authorization_scope

    client, db, worker, os, _ = system
    product = (await client.post("/company/products", json={"name": "Routine projects"})).json()
    manager = AsyncCompanyManager(db, os.registry) if isinstance(db, AsyncBaseDb) else CompanyManager(db, os.registry)
    with authorization_scope(lambda: _RoutineAuthorization(None, "routine")):
        project = await _manager_call(manager, "create_project", product_id=product["id"], name="Proposed release")
    assert project["status"] == "proposed"
    assert (await _manager_call(manager, "get_project", project["id"]))["product_id"] == product["id"]


@pytest.mark.asyncio
async def test_acceptance_budget_is_per_policy_and_distinct_task(system, tmp_path):
    from agno.company.execution import _call
    from agno.company.routines import _RoutineAuthorization
    from agno.run.authorization import authorization_scope

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path)
    executor, _ = await automation(system)
    first = await executor._accept(task)
    await _call(db, "transition_task", task["id"], "backlog", "Return proposal")
    returned = await _call(db, "get_task", task["id"])
    with pytest.raises(ValueError, match="fresh human acceptance"):
        await executor._accept(returned)
    # Storage counts distinct records even if a trusted caller repeats a receipt;
    # the automation boundary itself refuses to override a human withdrawal.
    repeated = await _call(
        db,
        "transition_task",
        task["id"],
        "ready",
        "Repeat receipt for budget accounting",
        executor_type="agent",
        executor_id="writer",
        expected_updated_at=returned["updated_at"],
        auto_accept=first["transitions"][-1]["auto_accept"],
    )
    assert repeated["status"] == "ready"
    assert sum(bool(entry.get("auto_accept")) for entry in repeated["transitions"]) == 2
    with authorization_scope(lambda: _RoutineAuthorization(None, routine["id"])):
        other = await intake_proposal(
            manager,
            "Another task",
            project_id=task["project_id"],
            evidence=task["evidence"],
        )
        third = await intake_proposal(
            manager,
            "Third task",
            project_id=task["project_id"],
            evidence=task["evidence"],
        )
    with pytest.raises(ValueError, match="limit"):
        await executor._accept(other)
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy["limits"]["max_acceptances"] = 2
    response = await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})
    assert response.status_code == 200, response.text
    # The edited policy has a fresh budget of two, not one remaining from its predecessor.
    second = await executor._accept(other)
    last = await executor._accept(third)
    assert second["status"] == last["status"] == "ready"
    assert second["transitions"][-1]["auto_accept"]["policy"] != first["transitions"][-1]["auto_accept"]["policy"]


@pytest.mark.asyncio
async def test_authenticated_intake_without_executor_is_picked_up_once(system, tmp_path):
    from unittest.mock import AsyncMock

    import jwt

    from agno.company.execution import _call
    from agno.os.authz import Authorization
    from agno.registry import Registry
    from agno.scheduler import ScheduleExecutor
    from agno.tools.company import CompanyTools

    _, db, worker, original_os, components = system
    path = tmp_path / "intake.md"
    path.write_text("# API release\nDocument the new API.\n")
    selected = {}
    writes = []

    class IntakeModel(OfflineModel):
        def invoke(self, messages, *args, **kwargs):
            observations = [message for message in messages if message.role == "tool"]
            if not observations:
                name = "read_product_source"
                arguments = {"source_id": selected["source_id"]}
            elif len(observations) == 1:
                index = json.loads(observations[0].content)
                name = "read_product_source"
                arguments = {"source_id": selected["source_id"], "path": index["data"][0]["path"]}
            elif len(observations) == 2:
                evidence = [json.loads(observations[1].content)]
                name = "intake_product_source"
                arguments = {
                    "source_id": selected["source_id"],
                    "title": "Document API",
                    "brief": "Write the release guide",
                    "proposal_key": "api-guide",
                    "evidence_links": [item["link"] for item in evidence],
                    "evidence_hashes": {item["link"]: item["content_hash"] for item in evidence},
                    # Model omission through empty or null arguments remains executor-less.
                    "executor_type": None,
                    "executor_id": "",
                    "project_id": selected["project_id"],
                }
            else:
                return ModelResponse(role="assistant", content="Proposal recorded", response_usage=MessageMetrics())
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": name,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
                response_usage=MessageMetrics(),
            )

    class WriterModel(OfflineModel):
        def invoke(self, *args, **kwargs):
            from agno.run.authorization import current_authorization

            writes.append(current_authorization().context.principal_id)
            return super().invoke(*args, **kwargs)

    writer = components["writer"]
    writer.model = WriterModel()
    reader = Agent(id="reader", model=IntakeModel(), tools=[CompanyTools(db)], db=db, telemetry=False)
    components["reader"] = reader
    secret = "authenticated-intake-secret-at-least-32-bytes"
    scopes = [
        f"{resource}:{action}"
        for resource in ("products", "projects", "tasks", "sources", "routines", "schedules", "wiki")
        for action in ("read", "write")
    ] + ["agents:reader:run", "agents:writer:run", "agents:read"]
    token = jwt.encode(
        {"sub": "alice", "aud": "intake-automation", "scopes": scopes, "exp": int(time.time()) + 3600},
        secret,
        algorithm="HS256",
    )
    os = AgentOS(
        id="intake-automation",
        db=db,
        registry=Registry(agents=[reader, writer]),
        company=CompanyConfig(),
        queue=worker.config,
        telemetry=False,
        user_isolation=True,
        authorization=Authorization(verification_keys=[secret], algorithm="HS256"),
    )
    app = os.get_app()
    app.state.queue_worker = worker
    app.state.internal_service_token = "test"
    worker.authorization_app = app
    worker._company_schedule_db = db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": "Bearer " + token}
    ) as client:
        product = (await client.post("/company/products", json={"name": "API"})).json()
        selected["project_id"] = (
            await client.post("/company/projects", json={"product_id": product["id"], "name": "Guide"})
        ).json()["id"]
        selected["source_id"] = (
            await client.post(
                "/company/sources", json={"product_id": product["id"], "type": "markdown", "reference": str(path)}
            )
        ).json()["id"]
        response = await client.post(
            "/company/routines",
            json={
                "product_id": product["id"],
                "name": "intake",
                "template": "intake",
                "executor_type": "agent",
                "executor_id": "reader",
                "cron_expr": "0 0 1 1 *",
                "auto_accept": {
                    "executor_type": "agent",
                    "executor_id": "writer",
                    "source_ids": [selected["source_id"]],
                    "limits": {"expires_at": int(time.time()) + 3600},
                },
            },
        )
        assert response.status_code == 201, response.text
        routine = response.json()
        original_request = client.request

        async def request_and_work(method, url, **kwargs):
            result = await original_request(method, url, **kwargs)
            if method == "POST" and result.status_code == 202:
                assert (await execute(worker))["status"] == "completed"
            return result

        intake = ScheduleExecutor(base_url="http://test", internal_service_token="test", poll_interval=0)
        intake._get_client = AsyncMock(return_value=SimpleClient(request_and_work))
        result = await intake.execute(await _call(db, "get_schedule", routine["id"]), db, release_schedule=False)
        assert result["status"] == "success", result
        rows, count = await _call(db, "get_tasks", product_id=product["id"])
        assert count == 1, result
        proposal = rows[0]
        assert proposal["status"] == "backlog" and proposal["executor_id"] is None
        assert proposal["executor_type"] is None and proposal["routine_id"] == routine["id"]
        executor, schedule = await automation((client, db, worker, os, components))
        ticks = await asyncio.gather(tick(executor, db), tick(executor, db))
        assert sum(value is not None for value in ticks) == 1
        task = await _call(db, "get_task", proposal["id"])
        assert task["status"] == "in_progress", ticks
        assert task["executor_id"] == "writer" and task["accepted_by"] == "alice"
        job = await worker.store.get_job(task["job_id"])
        assert job["user_id"] == "alice"
        assert job["idempotency_key"] == "company:" + task["id"] + ":1"
        assert (await execute(worker))["status"] == "completed"
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        await asyncio.gather(tick(executor, db), tick(executor, db))
        assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
        assert writes == ["alice"]
        assert (await _call(db, "get_task", task["id"]))["status"] == "in_review"
        history = (await client.get("/company/tasks/" + task["id"] + "/runs")).json()
        assert history["meta"]["total_count"] == 1


@pytest.mark.asyncio
async def test_exhausted_policy_skips_source_reads_on_every_tick(system, tmp_path, monkeypatch):
    import agno.company.sources as sources
    from agno.company.execution import _call
    from agno.company.routines import _RoutineAuthorization
    from agno.run.authorization import authorization_scope

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path)
    executor, schedule = await automation(system)
    reads = []
    original = sources.read_source

    def counted(source, run_id, *args, **kwargs):
        reads.append(run_id)
        return original(source, run_id, *args, **kwargs)

    monkeypatch.setattr(sources, "read_source", counted)
    await executor._accept(task)
    # Source bounds and the named evidence check share one fresh read.
    assert len(reads) == 1
    with authorization_scope(lambda: _RoutineAuthorization(None, routine["id"])):
        other = await intake_proposal(
            manager,
            "Another proposal",
            project_id=task["project_id"],
            evidence=task["evidence"],
        )
    # Deleted accepted Tasks still spend the budget, including after a restart.
    await _call(db, "transition_task", task["id"], "cancelled", "Archive accepted work")
    await _call(db, "delete_task", task["id"])
    executor, schedule = await automation(system)
    for _ in range(3):
        reads.clear()
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        result = await tick(executor, db)
        assert reads == []
        assert result["output"]["tasks"] == [
            {"task_id": other["id"], "status": "skipped", "reason": "Routine acceptance limit reached"}
        ]
        assert (await _call(db, "get_task", other["id"]))["status"] == "backlog"
        assert result["status"] == "success"
        assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 0
    # Editing the policy immediately opens its own budget; a skip is not cached forever.
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy["limits"]["max_acceptances"] = 2
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    await tick(executor, db)
    assert len(reads) == 1
    assert (await execute(worker))["status"] == "completed"


@pytest.mark.asyncio
async def test_automatic_checks_retry_when_server_fact_changes(system, tmp_path, monkeypatch):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path)
    executor, _ = await automation(system)
    await _call(db, "delete_project", task["project_id"])
    with pytest.raises(ValueError, match="project_active"):
        await executor._accept(task)
    with monkeypatch.context() as clock:
        clock.setattr(time, "time", lambda: (task["updated_at"] or task["created_at"]) + 1)
        await _call(db, "restore_project", task["project_id"])
    # A later restoration timestamp must refuse the stale proposal.
    with pytest.raises(ValueError, match="Proposal changed"):
        await executor._accept(task)
    task = await _call(db, "get_task", task["id"])
    assert (await executor._accept(task))["status"] == "ready"


@pytest.mark.asyncio
async def test_runtime_automation_schedule_rejects_public_mutation(system, tmp_path):
    from agno.company.execution import _call
    from agno.scheduler import ScheduleManager
    from agno.tools.scheduler import SchedulerTools

    client, db, worker, os, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    executor, schedule = await automation(system)
    path = "/schedules/" + schedule["id"]
    for response in [
        await client.patch(path, json={"enabled": False}),
        await client.patch(path, json={"cron_expr": "0 0 * * *"}),
        await client.delete(path),
        await client.post(path + "/enable"),
        await client.post(path + "/disable"),
        await client.post(path + "/trigger"),
    ]:
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "Company-managed schedules must be changed through /company/routines"
    manager = ScheduleManager(db)
    for method in ("update", "delete", "enable", "disable", "aupdate", "adelete", "aenable", "adisable"):
        with pytest.raises(ValueError, match="runtime-managed"):
            if method.startswith("a"):
                await getattr(manager, method)(schedule["id"])
            else:
                getattr(manager, method)(schedule["id"])
    tools = SchedulerTools(db=db)
    assert "runtime-managed" in json.loads(tools.disable_schedule(schedule["id"]))["error"]
    assert "runtime-managed" in json.loads(await tools.adisable_schedule(schedule["id"]))["error"]
    # User Routines still support the existing pause/resume domain.
    assert (await client.post("/company/routines/" + routine["id"] + "/pause")).status_code == 200
    assert (await client.post("/company/routines/" + routine["id"] + "/resume")).status_code == 200
    restarted, saved = await automation(system)
    assert saved["enabled"] is True
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    assert (await tick(restarted, db))["status"] == "success"
    assert (await execute(worker))["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["check", "executor"])
async def test_generic_schedule_cannot_bypass_company_policy_validation(system, tmp_path, invalid):
    import copy

    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path)
    before = await _call(db, "get_schedule", routine["id"])
    payload = copy.deepcopy(before["payload"])
    policy = payload["metadata"]["auto_accept"]
    if invalid == "check":
        policy["required_checks"] = ["unknown_check"]
    else:
        policy["executor_id"] = "missing-executor"
    response = await client.patch("/schedules/" + routine["id"], json={"payload": payload})
    assert response.status_code == 409, response.text
    assert (await _call(db, "get_schedule", routine["id"])) == before
    response = await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})
    assert response.status_code == 422, response.text
    assert (await _call(db, "get_schedule", routine["id"])) == before
    # Application checks use the same validation path as built-ins.
    os.company.acceptance_checks["application_check"] = lambda task, manager: True
    payload = copy.deepcopy(before["payload"])
    payload["metadata"]["auto_accept"]["required_checks"] = ["application_check"]
    response = await client.patch("/schedules/" + routine["id"], json={"payload": payload})
    assert response.status_code == 409, response.text
    assert (await _call(db, "get_schedule", routine["id"])) == before
    response = await client.patch(
        "/company/routines/" + routine["id"], json={"auto_accept": payload["metadata"]["auto_accept"]}
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_automation_filters_candidates_before_paging(system, monkeypatch):
    import inspect

    from agno.company.execution import _call

    client, db, worker, os, _ = system
    ready = await accepted(client)
    backlog = await accepted(client)
    await _call(db, "transition_task", backlog["id"], "backlog", "Revise")
    running = await accepted(client)
    executor, _ = await automation(system)
    await executor._dispatch(await _call(db, "get_task", running["id"]))
    # Enough terminal history to dominate an unfiltered page.
    for index in range(101):
        row = {
            **{key: value for key, value in ready.items() if key != "sandboxed"},
            "id": "completed-" + str(index),
            "status": "done",
        }
        await _call(db, "create_task", row)
    queries = []
    returned = []
    original = db.get_tasks

    def record(kwargs, result):
        queries.append(kwargs)
        returned.extend(row["id"] for row in result[0])
        return result

    def observed(**kwargs):
        return record(kwargs, original(**kwargs))

    async def aobserved(**kwargs):
        return record(kwargs, await original(**kwargs))

    monkeypatch.setattr(db, "get_tasks", aobserved if inspect.iscoroutinefunction(original) else observed)
    outcomes = await executor._tick()
    assert {query["status"] for query in queries} == {"backlog", "ready", "in_progress"}
    assert set(returned) == {ready["id"], backlog["id"], running["id"]}
    assert {outcome["task_id"] for outcome in outcomes} == {ready["id"], running["id"]}
    assert any(outcome["status"] == "already_submitted" for outcome in outcomes)


@pytest.mark.asyncio
async def test_refresh_completion_requires_permission_and_never_completes_on_archive(system, tmp_path):
    from agno.company.execution import _call
    from agno.company.routines import _manager_call

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path, template="refresh")
    await _manager_call(manager, "transition_task", task_id=task["id"], target="cancelled", reason="No longer needed")
    executor, schedule = await automation(system)
    # Terminal work alone is not a completion proposal.
    assert await executor._tick() == []
    refreshed = await _manager_call(manager, "refresh", task["product_id"])
    assert refreshed["completion_proposals"][0]["project_id"] == task["project_id"]
    outcomes = await executor._tick()
    assert outcomes == []
    project = await _manager_call(manager, "get_project", task["project_id"])
    proposal = await executor._completion_candidate(manager, project, routine["id"])
    assert proposal is not None
    with pytest.raises(ValueError, match="not authorized to complete Projects"):
        await executor._accept(proposal, completing=True)
    assert (await _manager_call(manager, "get_project", task["project_id"]))["status"] == "active"
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy["complete_projects"] = True
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    # Refresh may archive terminal records, but even an authorized Routine cannot
    # accept a Backlog Task or close an active Project itself.
    old = int(time.time()) - 30 * 86400
    await _call(
        db,
        "create_task",
        dict(
            id="old-terminal",
            product_id=task["product_id"],
            title="Old",
            status="done",
            created_at=old,
            updated_at=old,
            transitions=[],
        ),
    )
    independent = await _manager_call(manager, "create_project", product_id=task["product_id"], name="Human review")
    backlog = await _manager_call(
        manager, "create_task", product_id=task["product_id"], title="Needs human review", project_id=independent["id"]
    )
    refreshed = await _manager_call(manager, "refresh", task["product_id"])
    assert "old-terminal" in refreshed["archived_tasks"]
    assert (await _manager_call(manager, "get_task", backlog["id"]))["status"] == "backlog"
    assert (await _manager_call(manager, "get_project", task["project_id"]))["status"] == "active"
    assert (await _manager_call(manager, "get_task", task["id"]))["status"] == "cancelled"
    results = await asyncio.gather(tick(executor, db), tick(executor, db))
    assert sum(result is not None for result in results) == 1
    project = await _manager_call(manager, "get_project", task["project_id"])
    assert project["status"] == "done"
    assert len([entry for entry in project["transitions"] if entry["target"] == "done"]) == 1
    receipt = project["transitions"][-1]["auto_accept"]
    assert receipt["routine_id"] == routine["id"]
    assert await _call(db, "count_company_acceptances", routine["id"], receipt["policy"], "") == 1
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    assert await executor._tick() == []


@pytest.mark.asyncio
async def test_project_completion_and_task_acceptance_share_atomic_budget(system, tmp_path):
    from agno.company.execution import _call
    from agno.company.routines import _manager_call, _policy_fingerprint

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path, template="refresh")
    await _manager_call(manager, "transition_task", task_id=task["id"], target="cancelled", reason="Finished")
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy.update(complete_projects=True, required_checks=["has_source_evidence", "executor_registered"])
    independent = await _manager_call(manager, "create_project", product_id=task["product_id"], name="Independent work")
    policy["work_scope"]["project_ids"].append(independent["id"])
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    other = await intake_proposal(
        manager, "Independent task", task["evidence"], project_id=independent["id"], routine_id=routine["id"]
    )
    await _manager_call(manager, "refresh", task["product_id"])
    executor, _ = await automation(system)
    project = await _manager_call(manager, "get_project", task["project_id"])
    proposal = await executor._completion_candidate(manager, project, routine["id"])
    results = await asyncio.gather(
        executor._accept(other), executor._accept(proposal, completing=True), return_exceptions=True
    )
    assert sum(isinstance(result, dict) for result in results) == 1, results
    assert any("limit" in str(result) for result in results), results
    current = await _call(db, "get_schedule", routine["id"])
    assert await _call(db, "count_company_acceptances", routine["id"], _policy_fingerprint(current), "") == 1
    winner = next(result for result in results if isinstance(result, dict))
    if winner["status"] == "ready":
        await _call(db, "transition_task", winner["id"], "cancelled", "Archive accepted work")
    await _call(db, "delete_project" if winner["status"] == "done" else "delete_task", winner["id"])
    assert await _call(db, "count_company_acceptances", routine["id"], _policy_fingerprint(current), "") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "restriction", ["scope", "expiry", "revoked", "check", "source", "changed_task", "changed_project"]
)
async def test_project_completion_enforces_live_policy_and_terminal_tasks(system, tmp_path, monkeypatch, restriction):
    from agno.company.execution import _call
    from agno.company.routines import _manager_call

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path, template="refresh")
    await _manager_call(manager, "transition_task", task_id=task["id"], target="cancelled", reason="Finished")
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy["complete_projects"] = True
    if restriction == "scope":
        policy["work_scope"]["project_ids"] = []
    elif restriction == "expiry":
        policy["limits"]["expires_at"] = int(time.time()) + 3600
    elif restriction == "source":
        policy["source_ids"] = []
    elif restriction in {"check", "changed_task", "changed_project"}:

        async def check(proposal, check_manager):
            if restriction == "changed_project":
                with monkeypatch.context() as clock:
                    clock.setattr(time, "time", lambda: proposal["updated_at"] + 1)
                    await _call(db, "update_project", proposal["id"], name="Changed during checks")
                return True
            if restriction == "changed_task":
                await _call(
                    db,
                    "create_task",
                    dict(
                        id="new-open",
                        product_id=task["product_id"],
                        project_id=task["project_id"],
                        title="New work",
                        status="backlog",
                        created_at=int(time.time()),
                        transitions=[],
                    ),
                )
                return True
            return False

        os.company.acceptance_checks["completion_check"] = check
        policy["required_checks"].append("completion_check")
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    await _manager_call(manager, "refresh", task["product_id"])
    executor, _ = await automation(system)
    project = await _manager_call(manager, "get_project", task["project_id"])
    proposal = await executor._completion_candidate(manager, project, routine["id"])
    if restriction == "expiry":
        monkeypatch.setattr(time, "time", lambda: policy["limits"]["expires_at"])
    if restriction == "revoked":
        assert (
            await client.patch("/company/routines/" + routine["id"], json={"auto_accept": False})
        ).status_code == 200
    with pytest.raises(ValueError):
        await executor._accept(proposal, completing=True)
    assert (await _manager_call(manager, "get_project", task["project_id"]))["status"] == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["product_id", "template"])
async def test_completion_rechecks_routine_binding(system, tmp_path, binding):
    from agno.company.execution import _call
    from agno.company.routines import _manager_call, _policy_fingerprint

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path, template="refresh")
    await _manager_call(manager, "transition_task", task_id=task["id"], target="cancelled", reason="Finished")
    other = (await client.post("/company/products", json={"name": "Other"})).json()

    async def change_binding():
        current = await _call(db, "get_schedule", routine["id"])
        before = _policy_fingerprint(current)
        payload = current["payload"]
        payload["metadata"][binding] = other["id"] if binding == "product_id" else "intake"
        response = await client.patch("/schedules/" + routine["id"], json={"payload": payload})
        assert response.status_code == 409, response.text
        # Public mutation is blocked; model a concurrent application-level edit
        # to retain coverage of the acceptance boundary's final binding check.
        await _call(db, "update_schedule", routine["id"], payload=payload)
        assert _policy_fingerprint(await _call(db, "get_schedule", routine["id"])) == before

    async def check(proposal, check_manager):
        await change_binding()
        return True

    os.company.acceptance_checks["binding_check"] = check
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy.update(complete_projects=True, required_checks=["executor_registered", "binding_check"])
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    await _manager_call(manager, "refresh", task["product_id"])
    executor, _ = await automation(system)
    project = await _manager_call(manager, "get_project", task["project_id"])
    proposal = await executor._completion_candidate(manager, project, routine["id"])
    assert proposal is not None
    with pytest.raises(ValueError, match="Routine automatic acceptance changed"):
        await executor._accept(proposal, completing=True)
    assert (await _manager_call(manager, "get_project", task["project_id"]))["status"] == "active"
    current = await _call(db, "get_schedule", routine["id"])
    assert await _call(db, "count_company_acceptances", routine["id"], _policy_fingerprint(current), "") == 0


@pytest.mark.asyncio
async def test_automation_schedule_follows_company_lifespan(system, monkeypatch):
    from agno.company.execution import _call
    from agno.company.routines import _AUTOMATION_SCHEDULE_ID, _CompanyScheduleExecutor
    from agno.db.schemas.scheduler import Schedule
    from agno.os.app import scheduler_lifespan
    from agno.scheduler import SchedulePoller

    client, db, worker, os, _ = system
    app = worker.authorization_app
    company = os.company
    os._internal_service_token = "test"

    # Drive real claims deterministically, after the actual lifespan setup.
    async def start(poller):
        pass

    monkeypatch.setattr(SchedulePoller, "start", start)
    os.company = None
    async with scheduler_lifespan(app, os):
        assert await _call(db, "get_schedule", _AUTOMATION_SCHEDULE_ID) is None
    os.company = company
    async with scheduler_lifespan(app, os):
        assert (await _call(db, "get_schedule", _AUTOMATION_SCHEDULE_ID))["enabled"] is True
    await _call(db, "update_schedule", _AUTOMATION_SCHEDULE_ID, next_run_at=0)
    unrelated = Schedule(id="unrelated", name="Unrelated", cron_expr="* * * * *", endpoint="/health", next_run_at=0)
    await _call(db, "create_schedule", unrelated.to_dict())
    os.company = None
    for restart in range(2):
        async with scheduler_lifespan(app, os):
            disabled = await _call(db, "get_schedule", _AUTOMATION_SCHEDULE_ID)
            assert disabled["enabled"] is False
            assert disabled["disabled_reason"] == "company_off"
            claimed = await _call(db, "claim_due_schedule", "off-worker")
            if restart == 0:
                assert claimed is not None and claimed["id"] == unrelated.id
                await _call(db, "delete_schedule", unrelated.id)
            else:
                assert claimed is None
            assert await _call(db, "claim_due_schedule", "off-worker") is None
    os.company = company
    async with scheduler_lifespan(app, os):
        assert isinstance(app.state.scheduler_executor, _CompanyScheduleExecutor)
        assert app.state.scheduler_executor.company_db is os._company_db
        assert app.state.scheduler_executor.schedule_db is os.db
        assert (await _call(db, "get_schedule", _AUTOMATION_SCHEDULE_ID))["enabled"] is True
        result = await tick(app.state.scheduler_executor, db)
        assert result["status"] == "success", result
        saved = await _call(db, "get_schedule", _AUTOMATION_SCHEDULE_ID)
        assert saved["enabled"] is True and saved.get("disabled_reason") is None


@pytest.mark.asyncio
async def test_all_task_and_project_writes_stamp_updated_at(system, monkeypatch):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    product = (await client.post("/company/products", json={"name": "Timestamps"})).json()
    project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Project"})).json()
    project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Release"})).json()
    task = (
        await client.post(
            "/company/tasks", json={"product_id": product["id"], "project_id": project["id"], "title": "Task"}
        )
    ).json()
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now)

    async def write(method, *args, **kwargs):
        nonlocal now
        now += 1
        result = await _call(db, method, *args, **kwargs)
        assert result is not None
        assert result["updated_at"] == now, method
        return result

    await write("update_project", project["id"], name="Edited")
    await write("transition_project", project["id"], "active", "Start")
    await write("update_task", task["id"], brief="Edited")
    ready = await write("transition_task", task["id"], "ready", "Accept", executor_type="agent", executor_id="writer")
    running = await write("start_task_run", task["id"], 1, ready["transitions"])
    failed = await write("complete_task_run", task["id"], running["job_id"], {"status": "ERROR"})
    assert failed["status"] == "in_progress"
    assert await _call(db, "complete_task_run", task["id"], running["job_id"], {"status": "COMPLETED"}) is None
    assert await _call(db, "get_task", task["id"]) == failed
    running = await write("start_task_run", task["id"], 2, failed["transitions"])
    completed = await write("complete_task_run", task["id"], running["job_id"], {"status": "COMPLETED"})
    assert completed["status"] == "in_review"
    await write("transition_task", task["id"], "done", "Review accepted")
    await write("transition_project", project["id"], "done", "All work finished")
    # Direct and cascading archives/restores must stamp every affected child.
    for kind, record in (("task", task), ("project", project), ("product", product)):
        children = [("task", task)] if kind == "task" else [("task", task), ("project", project)]
        for method, archived in (("delete_", True), ("restore_", False)):
            now += 1
            assert await _call(db, method + kind, record["id"])
            for child_kind, child in children:
                saved = await _call(db, "get_" + child_kind, child["id"], include_deleted=True)
                assert saved["updated_at"] == now, (method, kind, child_kind)
                assert (saved["deleted_at"] is not None) is archived


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["task", "project"])
@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("timestamp", [None, 100])
async def test_transition_updated_at_compare_and_set(system, monkeypatch, kind, automatic, timestamp):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    product = (await client.post("/company/products", json={"name": "CAS"})).json()
    record = await _call(
        db,
        "create_" + kind,
        dict(
            id=str(uuid4()),
            product_id=product["id"],
            **(
                {"title": "Task", "status": "backlog", "routine_id": "routine"}
                if kind == "task"
                else {"name": "Project", "status": "active"}
            ),
            created_at=1,
            updated_at=timestamp,
            transitions=[],
        ),
    )
    if kind == "project":
        await _call(
            db,
            "create_task",
            dict(
                id=str(uuid4()),
                product_id=product["id"],
                project_id=record["id"],
                title="Finished",
                status="done",
                created_at=1,
                transitions=[],
            ),
        )
    options = {"executor_type": "agent", "executor_id": "writer"} if kind == "task" else {}
    target = "ready" if kind == "task" else "done"
    if automatic:
        options["auto_accept"] = {"routine_id": "routine", "policy": "version", "max_acceptances": 1}
        with pytest.raises(ValueError, match="requires expected_updated_at"):
            await _call(db, "transition_" + kind, record["id"], target, "Accept", **options)
    # Wrong timestamps (including NULL versus an integer) never transition.
    if timestamp is not None:
        assert (
            await _call(
                db, "transition_" + kind, record["id"], target, "Stale NULL", expected_updated_at=None, **options
            )
            is None
        )
    assert (
        await _call(db, "transition_" + kind, record["id"], target, "Stale", expected_updated_at=101, **options) is None
    )
    assert (await _call(db, "get_" + kind, record["id"]))["status"] == record["status"]
    monkeypatch.setattr(time, "time", lambda: 102)
    accepted = await _call(
        db, "transition_" + kind, record["id"], target, "Accept", expected_updated_at=timestamp, **options
    )
    assert accepted["status"] == target
    assert accepted["updated_at"] == 102
    if automatic:
        assert await _call(db, "count_company_acceptances", "routine", "version", "") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic", [False, True])
async def test_same_second_timestamp_keeps_status_guard(system, monkeypatch, automatic):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    product = (await client.post("/company/products", json={"name": "Epoch seconds"})).json()
    project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Release"})).json()
    task = (
        await client.post(
            "/company/tasks", json={"product_id": product["id"], "project_id": project["id"], "title": "First"}
        )
    ).json()
    monkeypatch.setattr(time, "time", lambda: 100)
    observed = await _call(db, "update_task", task["id"], title="Observed")
    await _call(db, "update_task", task["id"], title="Edited in the same second")
    options = dict(expected_updated_at=observed["updated_at"], executor_type="agent", executor_id="writer")
    if automatic:
        options["auto_accept"] = {"routine_id": "routine", "policy": "version", "max_acceptances": 2}
    accepted = await _call(db, "transition_task", task["id"], "ready", "Accept", **options)
    assert accepted["title"] == "Edited in the same second"
    assert accepted["updated_at"] == observed["updated_at"]
    with pytest.raises(ValueError, match="Invalid task transition"):
        await _call(db, "transition_task", task["id"], "ready", "Duplicate", **options)
    assert (
        len([entry for entry in (await _call(db, "get_task", task["id"]))["transitions"] if entry["target"] == "ready"])
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["title", "brief", "project_id", "evidence", "executor_id"])
async def test_automatic_task_timestamp_refuses_later_edit(system, monkeypatch, changed):
    from agno.company.execution import _call

    client, db, _, _, _ = system
    product = (await client.post("/company/products", json={"name": "Scope guard"})).json()
    project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Other"})).json()
    initial = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Initial"})).json()
    task = (
        await client.post(
            "/company/tasks", json={"product_id": product["id"], "project_id": initial["id"], "title": "Original"}
        )
    ).json()
    monkeypatch.setattr(time, "time", lambda: 100)
    observed = await _call(db, "update_task", task["id"], brief="Checked")
    values = {
        "title": "New",
        "brief": "New",
        "project_id": project["id"],
        "evidence": [{"source_id": "new"}],
        "executor_id": "other",
    }
    monkeypatch.setattr(time, "time", lambda: 101)
    edited = await _call(db, "update_task", task["id"], **{changed: values[changed]})
    assert edited["updated_at"] != observed["updated_at"]
    receipt = {"routine_id": "routine", "policy": "version", "max_acceptances": 1}
    result = await _call(
        db,
        "transition_task",
        task["id"],
        "ready",
        "Automatic acceptance",
        executor_type="agent",
        executor_id="writer",
        expected_updated_at=observed["updated_at"],
        auto_accept=receipt,
    )
    assert result is None
    assert (await _call(db, "get_task", task["id"]))["status"] == "backlog"
    assert await _call(db, "count_company_acceptances", "routine", "version", "") == 0


async def routine_executor(system):
    from unittest.mock import AsyncMock

    from agno.scheduler.executor import ScheduleExecutor

    client, _, worker, _, _ = system
    worker.authorization_app.state.internal_service_token = "contract-internal"

    async def request_and_work(method, url, **kwargs):
        response = await client.request(method, url, **kwargs)
        if method == "POST" and response.status_code == 202:
            job = await execute(worker)
            assert job["status"] == "completed", job
        return response

    executor = ScheduleExecutor(base_url="http://test", internal_service_token="contract-internal", poll_interval=0)
    executor._get_client = AsyncMock(return_value=SimpleClient(request_and_work))
    return executor


@pytest.mark.asyncio
async def test_template_free_routine_quiet_run_and_edited_executor(system):
    from agno.company.execution import _call

    client, db, _, _, components = system
    observed = []

    class CapturingModel(OfflineModel):
        def invoke(self, messages, *args, **kwargs):
            observed.append([message.content for message in messages if message.role == "user"])
            return super().invoke(messages, *args, **kwargs)

    components["writer"].model = CapturingModel()
    components["editors"].model = CapturingModel()
    product = (await client.post("/company/products", json={"name": "Quiet discovery"})).json()
    created = await client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="quiet",
            instructions="First custom instructions",
            executor_type="agent",
            executor_id="writer",
            cron_expr="0 * * * *",
        ),
    )
    assert created.status_code == 201, created.text
    routine = created.json()
    executor = await routine_executor(system)
    first = await executor.execute(await _call(db, "get_schedule", routine["id"]), db, release_schedule=False)
    assert first["status"] == "success", first
    assert any("First custom instructions" in str(value) for value in observed)
    edited = await client.patch(
        "/company/routines/" + routine["id"],
        json=dict(
            name="edited",
            instructions="Second custom instructions",
            executor_type="team",
            executor_id="editors",
            cron_expr="0 9 * * *",
        ),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["target_id"] == "editors" and edited.json()["target_type"] == "team"
    observed.clear()
    second = await executor.execute(await _call(db, "get_schedule", routine["id"]), db, release_schedule=False)
    assert second["status"] == "success", second
    assert any("Second custom instructions" in str(value) for value in observed)
    assert (await _call(db, "get_tasks", product_id=product["id"]))[1] == 0
    assert (await _call(db, "get_sources", product_id=product["id"]))[1] == 0
    history = (await client.get("/company/routines/" + routine["id"] + "/runs")).json()
    assert len(history["data"]) == 2 and all(row["status"] == "success" for row in history["data"])


@pytest.mark.asyncio
@pytest.mark.parametrize("executor_type,executor_id", [("agent", "writer"), ("team", "editors")])
async def test_search_routine_adds_website_and_deduplicates_three_runs(system, monkeypatch, executor_type, executor_id):
    from agno.company.execution import _call
    from agno.knowledge.document import Document
    from agno.tools.company import CompanyTools

    client, db, worker, os, components = system
    url = "https://example.test/discovered-release"
    monkeypatch.setattr(
        "agno.knowledge.reader.website_reader.WebsiteReader.read",
        lambda *args, **kwargs: [Document(content="The released API needs a migration guide.")],
    )
    product = (await client.post("/company/products", json={"name": "Search discovery"})).json()

    class SearchModel(OfflineModel):
        def invoke(self, messages, *args, **kwargs):
            results = [json.loads(message.content) for message in messages if message.role == "tool"]
            if not results:
                name, arguments = "add_product_source", dict(product_id=product["id"], reference=url)
            elif len(results) == 1:
                name, arguments = "read_product_source", dict(source_id=results[0]["id"], path=url)
            elif len(results) == 2:
                name, arguments = "list_company_projects", dict(product_id=product["id"])
            elif len(results) == 3 and not results[2]["data"]:
                name, arguments = "propose_company_project", dict(product_id=product["id"], name="Migration guide")
            elif len(results) == 3 or (len(results) == 4 and not results[2]["data"]):
                project = results[2]["data"][0] if results[2]["data"] else results[3]
                observed = results[1]
                assert "migration guide" in observed["content"]
                name, arguments = (
                    "intake_product_source",
                    dict(
                        source_id=results[0]["id"],
                        project_id=project["id"],
                        title="Write migration guide",
                        brief="Explain the released API migration",
                        proposal_key=observed["content_hash"],
                        evidence_links=[observed["link"]],
                        evidence_hashes={observed["link"]: observed["content_hash"]},
                    ),
                )
            else:
                return super().invoke(messages, *args, **kwargs)
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {"id": name, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
                ],
                response_usage=MessageMetrics(),
            )

    components[executor_id].model = SearchModel()
    components[executor_id].tools = [CompanyTools(db)]
    os.resync(worker.authorization_app)
    created = await client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="search",
            instructions="Discover useful pages, save website Sources, and propose evidence-backed work.",
            executor_type=executor_type,
            executor_id=executor_id,
            cron_expr="0 * * * *",
        ),
    )
    assert created.status_code == 201, created.text
    routine = created.json()
    executor = await routine_executor(system)
    runs = []
    for _ in range(3):
        result = await executor.execute(await _call(db, "get_schedule", routine["id"]), db, release_schedule=False)
        assert result["status"] == "success", result
        runs.append(result["run_id"])
    sources, count = await _call(db, "get_sources", product_id=product["id"])
    assert count == 1
    assert sources[0]["config"]["metadata"] == {executor_type + "_id": executor_id, "run_id": runs[0]}
    tasks, count = await _call(db, "get_tasks", product_id=product["id"])
    assert count == 1 and tasks[0]["status"] == "backlog"
    assert tasks[0]["evidence"][0]["run_id"] == runs[0]
    assert tasks[0]["evidence"][0]["link"] == url and tasks[0]["evidence"][0]["content_hash"]
    assert tasks[0]["routine_id"] == routine["id"]
    projects, project_count = await _call(db, "get_projects", product_id=product["id"])
    assert project_count == 1 and tasks[0]["project_id"] == projects[0]["id"]
    assert projects[0]["status"] == "proposed"
    listed = (await client.get("/company/sources", params={"product_id": product["id"]})).json()["data"]
    assert listed[0]["config"]["metadata"][executor_type + "_id"] == executor_id
    # Discovered websites use the same bounded acceptance checks as human-added Sources.
    policy = dict(
        executor_type=executor_type,
        executor_id=executor_id,
        source_ids=[sources[0]["id"]],
        required_checks=["has_source_evidence", "executor_registered"],
        limits={"expires_at": int(time.time()) + 3600},
    )
    authorized = await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})
    assert authorized.status_code == 200, authorized.text
    automatic, _ = await automation(system)
    assert (await automatic._accept(tasks[0]))["status"] == "ready"
    assert (await client.delete("/company/sources/" + sources[0]["id"])).status_code == 204
    assert (await client.get("/company/sources", params={"product_id": product["id"]})).json()["data"] == []


@pytest.mark.asyncio
async def test_template_free_policy_never_completes_projects(system, tmp_path):
    from agno.company.execution import _call
    from agno.company.routines import _manager_call, _policy_fingerprint

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path, template=None)
    assert routine["payload"]["metadata"]["template"] is None
    await _manager_call(manager, "transition_task", task_id=task["id"], target="cancelled", reason="Finished")
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy["complete_projects"] = True
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    await _manager_call(manager, "refresh", task["product_id"])
    executor, _ = await automation(system)
    project = await _manager_call(manager, "get_project", task["project_id"])
    proposal = await executor._completion_candidate(manager, project, routine["id"])
    assert proposal is not None
    with pytest.raises(ValueError, match="not authorized to complete Projects"):
        await executor._accept(proposal, completing=True)
    assert await executor._tick() == []
    assert (await _manager_call(manager, "get_project", project["id"]))["status"] == "active"
    current = await _call(db, "get_schedule", routine["id"])
    assert await _call(db, "count_company_acceptances", routine["id"], _policy_fingerprint(current), "") == 0


@pytest.mark.asyncio
async def test_routine_instruction_edit_preserves_fingerprint_and_spent_budget(system, tmp_path):
    from agno.company.execution import _call
    from agno.company.routines import _policy_fingerprint

    client, db, worker, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path)
    executor, _ = await automation(system)
    assert (await executor._accept(task))["status"] == "ready"
    before = await _call(db, "get_schedule", routine["id"])
    fingerprint = _policy_fingerprint(before)
    count = await _call(db, "count_company_acceptances", routine["id"], fingerprint, "")
    assert count == 1
    edited = await client.patch(
        "/company/routines/" + routine["id"], json={"instructions": "Use the revised review instructions."}
    )
    assert edited.status_code == 200, edited.text
    after = await _call(db, "get_schedule", routine["id"])
    assert after["payload"]["message"].endswith("Use the revised review instructions.")
    assert _policy_fingerprint(after) == fingerprint
    assert await _call(db, "count_company_acceptances", routine["id"], fingerprint, "") == count
    other = await intake_proposal(
        manager, "Another proposal", task["evidence"], project_id=task["project_id"], routine_id=routine["id"]
    )
    with pytest.raises(ValueError, match="acceptance limit reached"):
        await executor._accept(other)
    assert (await _call(db, "get_task", other["id"]))["status"] == "backlog"


@pytest.mark.asyncio
async def test_later_scope_move_cannot_accept_or_queue(system, tmp_path, monkeypatch):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    outside = (
        await client.post("/company/projects", json={"product_id": task["product_id"], "name": "Outside"})
    ).json()
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now)
    task = await _call(db, "update_task", task["id"], brief="Observed scope")

    async def move_task(observed, manager):
        monkeypatch.setattr(time, "time", lambda: now + 1)
        response = await client.patch("/company/tasks/" + task["id"], json={"project_id": outside["id"]})
        assert response.status_code == 200
        assert response.json()["updated_at"] != task["updated_at"]
        return True

    os.company.acceptance_checks["move_task"] = move_task
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy["required_checks"].append("move_task")
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    executor, _ = await automation(system)
    with pytest.raises(ValueError, match="changed during automatic acceptance"):
        await executor._accept(task)
    assert (await _call(db, "get_task", task["id"]))["status"] == "backlog"
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["add_terminal", "add_nonterminal", "archive_child", "edit_project"])
async def test_completion_uses_project_timestamp_and_terminal_task_gate(system, tmp_path, monkeypatch, change):
    from agno.company.execution import _call
    from agno.company.routines import _manager_call, _policy_fingerprint

    client, db, _, os, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path, template="refresh")
    await _manager_call(manager, "transition_task", task_id=task["id"], target="cancelled", reason="Finished")
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now)
    await _call(db, "update_project", task["project_id"], name="Observed")

    async def change_facts(proposal, check_manager):
        if change in {"add_terminal", "add_nonterminal"}:
            await _call(
                db,
                "create_task",
                dict(
                    id=str(uuid4()),
                    product_id=task["product_id"],
                    project_id=task["project_id"],
                    title="New child",
                    status="cancelled" if change == "add_terminal" else "backlog",
                    created_at=now,
                    evidence=task["evidence"],
                    transitions=[],
                ),
            )
        elif change == "archive_child":
            assert await _call(db, "delete_task", task["id"])
        else:
            monkeypatch.setattr(time, "time", lambda: now + 1)
            updated = await _call(db, "update_project", task["project_id"], name="Changed later")
            assert updated["updated_at"] != proposal["updated_at"]
        return True

    os.company.acceptance_checks["change_facts"] = change_facts
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy.update(complete_projects=True)
    policy["required_checks"].append("change_facts")
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    await _manager_call(manager, "refresh", task["product_id"])
    executor, _ = await automation(system)
    project = await _manager_call(manager, "get_project", task["project_id"])
    proposal = await executor._completion_candidate(manager, project, routine["id"])
    assert proposal is not None
    refused = change in {"add_nonterminal", "edit_project"}
    if refused:
        reason = "Project has open Tasks" if change == "add_nonterminal" else "changed during automatic acceptance"
        with pytest.raises(ValueError, match=reason):
            await executor._accept(proposal, completing=True)
    else:
        # Completion guards the Project timestamp and current terminal status,
        # without comparing the child set with the earlier proposal snapshot.
        assert (await executor._accept(proposal, completing=True))["status"] == "done"
    assert (await _call(db, "get_project", project["id"]))["status"] == ("active" if refused else "done")
    schedule = await _call(db, "get_schedule", routine["id"])
    assert await _call(db, "count_company_acceptances", routine["id"], _policy_fingerprint(schedule), "") == (
        0 if refused else 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "create", "upsert"])
async def test_python_schedule_writes_strip_forged_grants(system, tmp_path, operation):
    import copy

    from agno.company.execution import _call
    from agno.db.base import AsyncBaseDb
    from agno.os.auth import _default_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.run.authorization import RunAuthorization, authorization_scope
    from agno.scheduler import ScheduleManager

    client, db, worker, os, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    schedules = ScheduleManager(db)
    before = await _call(db, "get_schedule", routine["id"])
    payload = copy.deepcopy(before["payload"])
    payload["_agno_company_acceptance"] = {
        "user_id": "mallory",
        "_agno_authorization": {
            "context": {"principal_id": "mallory", "scopes": ["agent_os:admin"]},
            "service_account": False,
        },
    }
    caller = RunAuthorization(
        _default_authorization_provider(),
        AuthorizationContext(principal_id="editor", scopes=["schedules:write", "agents:run"]),
    )
    with authorization_scope(lambda: caller):
        if operation == "update":
            updated = (
                await schedules.aupdate(routine["id"], payload=payload)
                if isinstance(db, AsyncBaseDb)
                else schedules.update(routine["id"], payload=payload)
            )
        else:
            args = dict(
                name=before["name"] if operation == "upsert" else "forged",
                cron="0 * * * *",
                endpoint="/agents/writer/runs",
                payload=payload,
                if_exists="update",
                provenance={"managed_by": "company"},
            )
            updated = await schedules.acreate(**args) if isinstance(db, AsyncBaseDb) else schedules.create(**args)
    stored = await _call(db, "get_schedule", updated.id)
    assert "_agno_company_acceptance" not in stored["payload"]
    assert stored["payload"]["_agno_authorization"]["context"]["principal_id"] == "editor"
    if operation != "create":
        executor, _ = await automation(system)
        os.authorization = True
        try:
            with pytest.raises(ValueError, match="no human automatic acceptance authorization"):
                await executor._accept(task)
        finally:
            os.authorization = False
        assert (await _call(db, "get_task", task["id"]))["status"] == "backlog"
        assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    # Trusted HTTP updates still issue fresh grants after the manager boundary.
    response = await client.patch(
        "/company/routines/" + routine["id"], json={"auto_accept": before["payload"]["metadata"]["auto_accept"]}
    )
    assert response.status_code == 200, response.text
    assert "_agno_company_acceptance" in (await _call(db, "get_schedule", routine["id"]))["payload"]


@pytest.mark.asyncio
async def test_revoked_ready_acceptance_returns_to_visible_backlog(system, tmp_path):
    from agno.company.execution import _call

    client, db, worker, _, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    executor, schedule = await automation(system)
    accepted_task = await executor._accept(task)
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": False})).status_code == 200
    with pytest.raises(ValueError, match="changed or revoked"):
        await executor._dispatch(accepted_task)
    saved = await _call(db, "get_task", task["id"])
    assert saved["status"] == "backlog" and saved["accepted_by"] is None
    assert "changed or revoked" in saved["transitions"][-1]["reason"]
    assert (await client.get("/company/attention")).json()["proposals"] == 1
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None


@pytest.mark.asyncio
async def test_cheap_check_failure_skips_source_io(system, tmp_path, monkeypatch):
    from unittest.mock import Mock

    from agno.company.execution import _call

    client, db, _, _, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    assert (
        await client.post(
            "/company/projects/" + task["project_id"] + "/transitions",
            json={"target": "cancelled", "reason": "Dropped"},
        )
    ).status_code == 200
    read = Mock(side_effect=AssertionError("Source must not be read"))
    monkeypatch.setattr("agno.company.sources.read_source", read)
    executor, schedule = await automation(system)
    for _ in range(3):
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        result = await tick(executor, db)
        assert "project_active" in result["output"]["tasks"][0]["reason"]
    read.assert_not_called()


@pytest.mark.asyncio
async def test_expired_authorization_refused_at_write(system):
    client, db, _, _, _ = system
    product = (await client.post("/company/products", json={"name": "Expiry"})).json()
    response = await client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="Expired",
            instructions="Check",
            executor_type="agent",
            executor_id="writer",
            cron_expr="0 * * * *",
            auto_accept=dict(executor_type="agent", executor_id="writer", limits={"expires_at": 1}),
        ),
    )
    assert response.status_code == 422
    assert "future" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["remote", "no_database"])
async def test_automatic_policy_refuses_unrunnable_executor(system, tmp_path, monkeypatch, kind):
    from agno.agent import RemoteAgent
    from agno.company.execution import _call

    client, db, _, os, components = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    if kind == "remote":
        remote = RemoteAgent(base_url="http://127.0.0.1:1", agent_id="writer")
        original = os.registry.get_agent
        monkeypatch.setattr(os.registry, "get_agent", lambda name: remote if name == "writer" else original(name))
    else:
        monkeypatch.setattr(components["writer"], "db", None)
    policy = routine["payload"]["metadata"]["auto_accept"]
    response = await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})
    assert response.status_code == 422, response.text
    executor, _ = await automation(system)
    with pytest.raises(ValueError, match="local executor|requires a database"):
        await executor._accept(task)
    assert (await _call(db, "get_task", task["id"]))["status"] == "backlog"


@pytest.mark.asyncio
@pytest.mark.parametrize("successor_worker", ["first", "second"])
async def test_expired_tick_cannot_accept_or_release_new_claim(system, tmp_path, monkeypatch, successor_worker):
    from unittest.mock import Mock

    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    executor, schedule = await automation(system)
    claimed = await _call(db, "claim_due_schedule", "first")
    assert claimed["id"] == schedule["id"]

    async def slow_check(observed, manager):
        # Model process suspension or slow IO beyond the default lock grace.
        monkeypatch.setattr(time, "time", lambda: claimed["locked_at"] + 301)
        second = await _call(db, "claim_due_schedule", successor_worker)
        assert second["id"] == claimed["id"]
        assert second["locked_at"] != claimed["locked_at"]
        return True

    os.company.acceptance_checks["slow_check"] = slow_check
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy["required_checks"].append("slow_check")
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    read = Mock(side_effect=AssertionError("An expired tick must not start another Source read"))
    monkeypatch.setattr("agno.company.sources.read_source", read)
    result = await executor.execute(claimed, db)
    assert "claim budget" in str(result)
    read.assert_not_called()
    assert (await _call(db, "get_task", task["id"]))["status"] == "backlog"
    successor = await _call(db, "get_schedule", schedule["id"])
    assert successor["locked_by"] == successor_worker
    assert successor["locked_at"] == claimed["locked_at"] + 301
    assert successor["next_run_at"] == claimed["next_run_at"]
    assert await _call(
        db, "release_schedule", schedule["id"], worker_id=successor_worker, locked_at=successor["locked_at"]
    )
    assert (await _call(db, "get_schedule", schedule["id"]))["locked_by"] is None
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None


@pytest.mark.asyncio
async def test_runtime_automation_schedule_rejects_upsert_and_tool_creation(system):
    from agno.company.execution import _call
    from agno.scheduler import ScheduleManager
    from agno.tools.scheduler import SchedulerTools

    _, db, _, _, _ = system
    _, schedule = await automation(system)
    manager = ScheduleManager(db)
    tools = SchedulerTools(db=db)
    arguments = dict(name=schedule["name"], cron="* * * * *", endpoint="/agents/writer/runs")
    before = await _call(db, "get_schedule", schedule["id"])
    try:
        for asynchronous in (False, True):
            with pytest.raises(ValueError, match="runtime-managed"):
                if asynchronous:
                    await manager.acreate(**arguments, if_exists="update")
                else:
                    manager.create(**arguments, if_exists="update")
            tool_arguments = {**arguments, "payload": json.dumps({"message": "Scheduled work"})}
            result = (
                await tools.acreate_schedule(**tool_arguments)
                if asynchronous
                else tools.create_schedule(**tool_arguments)
            )
            assert "runtime-managed" in json.loads(result)["error"]
            assert await _call(db, "get_schedule", schedule["id"]) == before
        # Read-only create-or-skip remains idempotent; reconciliation still works.
        assert (await manager.acreate(**arguments, if_exists="skip")).id == schedule["id"]
        _, reconciled = await automation(system)
        assert reconciled["endpoint"] == "/company/attention"
        assert reconciled["enabled"] is True
    finally:
        manager.close()
        tools.manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
@pytest.mark.parametrize("operation", ["trigger", "metadata"])
async def test_schedule_metadata_changes_preserve_human_acceptance_grant(system, tmp_path, authorized, operation):
    from agno.company.execution import _call
    from agno.os.auth import _default_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.run.authorization import RunAuthorization, authorization_scope
    from agno.tools.scheduler import SchedulerTools

    _, db, _, _, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    before = await _call(db, "get_schedule", routine["id"])
    tools = SchedulerTools(db=db)
    caller = RunAuthorization(
        _default_authorization_provider(),
        AuthorizationContext(principal_id="editor", scopes=["schedules:write", "agents:run"]),
    )
    try:
        with authorization_scope(lambda: caller if authorized else None):
            if operation == "trigger":
                result = (
                    await tools.atrigger_schedule(routine["id"])
                    if isinstance(db, AsyncBaseDb)
                    else tools.trigger_schedule(routine["id"])
                )
                assert json.loads(result)["status"] == "triggered"
                assert "_agno_company_acceptance" not in result
            elif isinstance(db, AsyncBaseDb):
                await tools.manager.aupdate(routine["id"], description="Scheduling metadata only")
            else:
                tools.manager.update(routine["id"], description="Scheduling metadata only")
        after = await _call(db, "get_schedule", routine["id"])
        assert after["payload"]["_agno_company_acceptance"] == before["payload"]["_agno_company_acceptance"]
        assert after["payload"]["metadata"]["auto_accept"] == before["payload"]["metadata"]["auto_accept"]
        executor, _ = await automation(system)
        assert (await executor._accept(task))["status"] == "ready"
    finally:
        tools.manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
async def test_human_backlog_withdrawal_requires_fresh_human_acceptance(system, tmp_path, queued):
    from agno.company.execution import _call
    from agno.company.routines import _policy_fingerprint

    client, db, worker, _, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    executor, schedule = await automation(system)
    if queued:
        await tick(executor, db)
    else:
        await executor._accept(task)
    response = await client.post(
        "/company/tasks/" + task["id"] + "/transitions", json={"target": "backlog", "reason": "Human withdrew scope"}
    )
    assert response.status_code == 200, response.text
    withdrawn = await _call(db, "get_task", task["id"])
    assert withdrawn["status"] == "backlog"
    if queued:
        assert (await execute(worker))["status"] == "failed"
    for _ in range(2):
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        result = await tick(executor, db)
        assert "fresh human acceptance" in result["output"]["tasks"][0]["reason"]
        saved = await _call(db, "get_task", task["id"])
        assert saved["status"] == "backlog"
        assert saved["transitions"] == withdrawn["transitions"]
        assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
    # Fresh human acceptance permits pickup at the next unused attempt.
    response = await client.post(
        "/company/tasks/" + task["id"] + "/transitions",
        json={
            "target": "ready",
            "reason": "Human accepted revised scope",
            "executor_type": "agent",
            "executor_id": "writer",
        },
    )
    assert response.status_code == 200, response.text
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    outcome = await tick(executor, db)
    assert outcome["status"] == "success", outcome
    assert (await execute(worker))["status"] == "completed"
    current = await _call(db, "get_task", task["id"])
    attempts = [entry["attempt"] for entry in current["transitions"] if entry.get("attempt")]
    assert attempts == ([1, 2] if queued else [1])
    stored = await _call(db, "get_schedule", routine["id"])
    assert await _call(db, "count_company_acceptances", routine["id"], _policy_fingerprint(stored), "") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("isolation", [False, True], ids=["shared", "isolated"])
@pytest.mark.parametrize("phase", ["write_token", "write_managed", "before_checks", "during_checks", "legacy_token"])
async def test_automatic_acceptance_requires_wiki_read(system, tmp_path, isolation, phase):
    import copy

    import jwt

    from agno.company.execution import _call
    from agno.company.manager import AsyncCompanyManager, CompanyManager
    from agno.company.routines import _manager_call, _policy_fingerprint
    from agno.os.authz import Authorization
    from agno.registry import Registry
    from agno.run.authorization import AUTHORIZATION_KEY

    _, db, worker, _, components = system
    secret = "wiki-acceptance-tests-secret-at-least-32-bytes"
    scopes = [
        f"{resource}:{action}"
        for resource in ("products", "tasks", "routines", "schedules")
        for action in ("read", "write")
    ] + ["agents:writer:run", "wiki:read"]
    managed = phase in {"write_managed", "before_checks", "during_checks"}
    # The identity store is independent of the four Company storage adapters.
    auth_db = SqliteDb(db_file=str(tmp_path / "wiki-authority.db"))
    authz = Authorization(db=auth_db if managed else None, verification_keys=[secret], algorithm="HS256")
    if managed:
        authz.define_role("admin", ["agent_os:admin"])
        authz.define_role("runner", scopes)
        authz.define_role("without_wiki", [scope for scope in scopes if scope != "wiki:read"])
        authz.seed(admin="root")
        authz.assign("alice", "without_wiki" if phase == "write_managed" else "runner")

    def headers(with_wiki=True):
        claims = dict(sub="alice", aud="wiki-acceptance", exp=int(time.time()) + 3600)
        if not managed:
            claims["scopes"] = scopes if with_wiki else [scope for scope in scopes if scope != "wiki:read"]
        return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}

    checks_run = []
    revoke_during_check = phase == "during_checks"

    async def required_check(proposal, manager):
        checks_run.append(proposal["id"])
        if revoke_during_check:
            await authz.aset_role("alice", "without_wiki")
        return True

    os = AgentOS(
        id="wiki-acceptance",
        db=db,
        registry=Registry(agents=[components["writer"]]),
        company=CompanyConfig(acceptance_checks={"application_check": required_check}),
        queue=worker.config,
        telemetry=False,
        user_isolation=isolation,
        authorization=authz,
    )
    app = os.get_app()
    app.state.queue_worker = worker
    app.state.internal_service_token = "test"
    worker.authorization_app = app
    worker._company_schedule_db = db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers(phase != "write_token")
        ) as client:
            product_response = await client.post("/company/products", json={"name": "Wiki-gated work"})
            assert product_response.status_code == 201, product_response.text
            product = product_response.json()
            policy = dict(
                executor_type="agent",
                executor_id="writer",
                required_checks=["executor_registered", "application_check"],
                limits={"max_acceptances": 1, "expires_at": int(time.time()) + 3600},
            )
            body = dict(
                product_id=product["id"],
                name="intake",
                template="intake",
                executor_type="agent",
                executor_id="writer",
                cron_expr="0 0 1 1 *",
                auto_accept=policy,
            )
            if phase.startswith("write_"):
                refused = await client.post("/company/routines", json=body)
                assert refused.status_code == 403 and "wiki" in refused.text, refused.text
                assert await _call(db, "get_schedule_by_name", product["id"] + ".intake", user_id="alice") is None
                created = await client.post("/company/routines", json={**body, "auto_accept": False})
                assert created.status_code == 201, created.text
                routine = created.json()
                before = await _call(db, "get_schedule", routine["id"])
                refused = await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})
                assert refused.status_code == 403 and "wiki" in refused.text, refused.text
                assert await _call(db, "get_schedule", routine["id"]) == before
                if managed:
                    await authz.aset_role("alice", "runner")
                client.headers.update(headers())
                accepted = await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})
                assert accepted.status_code == 200, accepted.text
            else:
                created = await client.post("/company/routines", json=body)
                assert created.status_code == 201, created.text
                routine = created.json()
            manager = (
                AsyncCompanyManager(db, os.registry) if isinstance(db, AsyncBaseDb) else CompanyManager(db, os.registry)
            )
            project = await _manager_call(manager, "create_project", product_id=product["id"], name="Routine work")
            task = await _manager_call(
                manager,
                "create_task",
                product_id=product["id"],
                title="Routine proposal",
                project_id=project["id"],
                user_id="alice",
                origin="routine",
                routine_id=routine["id"],
            )
            stored = await _call(db, "get_schedule", routine["id"])
            fingerprint = _policy_fingerprint(stored)
            if phase == "before_checks":
                await authz.aset_role("alice", "without_wiki")
            elif phase == "legacy_token":
                # A grant persisted by older code may lack the dispatch permission.
                payload = copy.deepcopy(stored["payload"])
                payload["_agno_company_acceptance"][AUTHORIZATION_KEY]["context"]["scopes"].remove("wiki:read")
                await _call(db, "update_schedule", routine["id"], payload=payload)
            executor, schedule = await automation((client, db, worker, os, components))
            if not phase.startswith("write_"):
                result = await tick(executor, db)
                assert "wiki:read" in result["output"]["tasks"][0]["reason"], result
                saved = await _call(db, "get_task", task["id"])
                assert saved["status"] == "backlog" and saved["job_id"] is None
                assert not saved["transitions"]
                assert await _call(db, "count_company_acceptances", routine["id"], fingerprint, "") == 0
                assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
                assert checks_run == ([task["id"]] if phase == "during_checks" else [])
                revoke_during_check = False
                if managed:
                    await authz.aset_role("alice", "runner")
                else:
                    restored = await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})
                    assert restored.status_code == 200, restored.text
            await _call(db, "update_schedule", schedule["id"], next_run_at=0)
            await tick(executor, db)
            assert (await execute(worker))["status"] == "completed"
            saved = await _call(db, "get_task", task["id"])
            assert saved["status"] == "in_review"
            assert saved["transitions"][-2]["started_by"] == "alice"
            assert await _call(db, "count_company_acceptances", routine["id"], fingerprint, "") == 1
    finally:
        auth_db.close()


@pytest.mark.asyncio
async def test_quiet_automation_history_and_dispatch(system):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    executor, schedule = await automation(system)
    before = (await client.get("/company/attention")).json()
    for _ in range(10):
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        assert (await tick(executor, db))["status"] == "success"
    assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 0
    assert (await client.get("/company/attention")).json() == before
    await accepted(client)
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    await tick(executor, db)
    rows, total = await _call(db, "get_schedule_runs", schedule["id"])
    assert total == 1 and rows[0]["status"] == "success"
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    await tick(executor, db)
    assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ERROR", "CANCELLED"])
async def test_automation_does_not_repost_retained_result(system, monkeypatch, status):
    from unittest.mock import AsyncMock

    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    await tick(executor, db)
    saved = await _call(db, "get_task", task["id"])
    await _call(db, "complete_task_run", task["id"], saved["job_id"], {"status": status})
    table = worker.config.db._get_table("jobs")
    with worker.config.db.Session() as session, session.begin():
        session.execute(table.delete().where(table.c.id == saved["job_id"]))
    before = (await client.get("/company/attention")).json()
    assert before["failed"] == 1
    dispatch = AsyncMock(side_effect=AssertionError("Failed attempts must not be posted"))
    monkeypatch.setattr(executor, "_dispatch", dispatch)
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    await tick(executor, db)
    dispatch.assert_not_called()
    assert (await client.get("/company/attention")).json() == before
    assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 1


@pytest.mark.asyncio
async def test_automation_records_raised_tick_and_preserves_other_disable_reason(system, monkeypatch):
    from unittest.mock import AsyncMock

    from agno.company.execution import _call
    from agno.company.routines import _ensure_automation_schedule

    _, db, _, _, _ = system
    executor, schedule = await automation(system)
    monkeypatch.setattr(executor, "_tick", AsyncMock(side_effect=RuntimeError("storage unavailable")))
    result = await tick(executor, db)
    assert result["status"] == "failed" and result["error"] == "storage unavailable"
    assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 1
    await _call(db, "update_schedule", schedule["id"], enabled=False, disabled_reason="operator")
    saved = await _ensure_automation_schedule(db)
    assert saved["enabled"] is False and saved["disabled_reason"] == "operator"


@pytest.mark.asyncio
async def test_automation_schedule_runs_hourly_and_migrates_minute_rows(system):
    from agno.company.execution import _call
    from agno.company.routines import _ensure_automation_schedule

    _, db, _, _, _ = system
    _, schedule = await automation(system)
    assert schedule["cron_expr"] == "0 * * * *"
    await _call(db, "update_schedule", schedule["id"], cron_expr="* * * * *")
    saved = await _ensure_automation_schedule(db)
    assert saved["cron_expr"] == "0 * * * *"
    assert (await _call(db, "get_schedule", schedule["id"]))["cron_expr"] == "0 * * * *"


@pytest.mark.asyncio
async def test_automation_schedule_cron_is_configurable(system):
    from agno.company.execution import _call
    from agno.company.routines import _ensure_automation_schedule

    _, db, _, _, _ = system
    _, schedule = await automation(system)
    await _call(db, "update_schedule", schedule["id"], next_run_at=int(time.time()) + 3600)
    saved = await _ensure_automation_schedule(db, cron_expr="*/5 * * * *")
    assert saved["cron_expr"] == "*/5 * * * *" and int(time.time()) < saved["next_run_at"] <= int(time.time()) + 300
    await _ensure_automation_schedule(db, cron_expr="*/5 * * * *")
    assert (await _call(db, "get_schedule", schedule["id"]))["next_run_at"] == saved["next_run_at"]
    with pytest.raises(ValueError, match="Invalid cron expression"):
        await _ensure_automation_schedule(db, cron_expr="every hour")


@pytest.mark.asyncio
async def test_company_config_database_and_disabled_section(system):
    from agno.os.config import AgentOSConfig, CompanyDomainConfig, CompanySectionConfig, DatabaseConfig

    client, db, _, os, _ = system
    section = (await client.get("/config")).json()["company"]
    tables = [db.products_table_name, db.projects_table_name, db.tasks_table_name, db.sources_table_name]
    assert section["dbs"] == [{"db_id": db.id, "domain_config": {"display_name": db.id}, "tables": tables}]
    os.config = AgentOSConfig(
        company=CompanySectionConfig(
            display_name="Work",
            dbs=[
                DatabaseConfig(db_id="unrelated", tables=["hidden"]),
                DatabaseConfig(db_id=db.id, domain_config=CompanyDomainConfig(display_name="Company records")),
            ],
        )
    )
    configured = (await client.get("/config")).json()["company"]
    assert configured["display_name"] == "Work"
    assert configured["dbs"] == [
        {"db_id": db.id, "domain_config": {"display_name": "Company records"}, "tables": tables}
    ]
    os.company = None
    assert (await client.get("/config")).json()["company"] is None


@pytest.mark.asyncio
async def test_company_executor_preserves_regular_schedule_history(system, monkeypatch):
    from agno.company.execution import _call
    from agno.db.schemas.scheduler import Schedule
    from agno.scheduler import ScheduleExecutor

    _, db, _, _, _ = system
    executor, _ = await automation(system)
    regular = Schedule(id="regular", name="Regular", cron_expr="* * * * *", endpoint="/health")
    await _call(db, "create_schedule", regular.to_dict())

    async def endpoint(self, schedule):
        rows, total = await _call(db, "get_schedule_runs", schedule.id)
        assert total == 1 and rows[0]["status"] == "running"
        return {"status": "success"}

    monkeypatch.setattr(ScheduleExecutor, "_call_endpoint", endpoint)
    assert (await executor.execute(regular, db))["status"] == "success"
    rows, total = await _call(db, "get_schedule_runs", regular.id)
    assert total == 1 and rows[0]["status"] == "success"


@pytest.mark.asyncio
async def test_company_config_uses_explicit_company_database_only(system):
    _, db, _, _, _ = system
    unrelated = SqliteDb(id="unrelated", db_file=":memory:")
    os = AgentOS(db=unrelated, company=CompanyConfig(db=db), telemetry=False)
    async with AsyncClient(transport=ASGITransport(app=os.get_app()), base_url="http://test") as client:
        section = (await client.get("/config")).json()["company"]
    assert [entry["db_id"] for entry in section["dbs"]] == [db.id]
    assert section["dbs"][0]["tables"] == [
        db.products_table_name,
        db.projects_table_name,
        db.tasks_table_name,
        db.sources_table_name,
    ]


@pytest.mark.asyncio
async def test_unmanaged_schedule_endpoint_updates_target_columns(system):
    from agno.company.execution import _call

    client, db, _, _, _ = system
    response = await client.post(
        "/schedules",
        json={
            "name": "Generic",
            "endpoint": "/agents/writer/runs",
            "cron_expr": "0 * * * *",
        },
    )
    assert response.status_code == 201, response.text
    schedule_id = response.json()["id"]
    await _call(db, "stamp_schedule_provenance", schedule_id, target_type="agent", target_id="writer")
    for endpoint, kind, target_id in [
        ("/teams/editors/runs/", "team", "editors"),
        ("/workflows/draft/runs", "workflow", "draft"),
        ("/health", None, None),
    ]:
        response = await client.patch("/schedules/" + schedule_id, json={"endpoint": endpoint})
        assert response.status_code == 200, response.text
        saved = await _call(db, "get_schedule", schedule_id)
        assert (saved["target_type"], saved["target_id"]) == (kind, target_id)
        assert saved["managed_by"] is None
    # Storage cannot independently rewrite the target or contradict an endpoint.
    for updates in [
        {"target_id": "writer"},
        {"endpoint": "/teams/editors/runs", "target_type": "agent", "target_id": "writer"},
    ]:
        with pytest.raises(ValueError, match="update_schedule cannot modify"):
            await _call(db, "update_schedule", schedule_id, **updates)


@pytest.mark.asyncio
async def test_routine_endpoint_edit_rejects_nonrun_target(system):
    from agno.company.execution import _call

    client, db, _, _, _ = system
    product = (await client.post("/company/products", json={"name": "Routine targets"})).json()
    response = await client.post(
        "/company/routines",
        json={
            "product_id": product["id"],
            "name": "Routine",
            "instructions": "Review work",
            "executor_type": "agent",
            "executor_id": "writer",
            "cron_expr": "0 * * * *",
        },
    )
    assert response.status_code == 201, response.text
    schedule_id = response.json()["id"]
    patched = await client.patch("/schedules/" + schedule_id, json={"endpoint": "/teams/editors/runs"})
    assert patched.status_code == 409, patched.text
    saved = await _call(db, "get_schedule", schedule_id)
    assert (saved["target_type"], saved["target_id"]) == ("agent", "writer")
    changed = await client.patch(
        "/company/routines/" + schedule_id, json={"executor_type": "team", "executor_id": "editors"}
    )
    assert changed.status_code == 200, changed.text
    saved = await _call(db, "get_schedule", schedule_id)
    assert (saved["target_type"], saved["target_id"]) == ("team", "editors")
    refused = await client.patch("/schedules/" + schedule_id, json={"endpoint": "/health"})
    assert refused.status_code == 409, refused.text
    assert (await _call(db, "get_schedule", schedule_id))["endpoint"] == saved["endpoint"]


@pytest.mark.asyncio
async def test_automation_cancels_reserved_attempt_without_job_or_result(system):
    from agno.company.execution import _call

    client, db, worker, _, _ = system
    task = await accepted(client)
    current = await _call(db, "get_task", task["id"])
    reserved = await _call(db, "start_task_run", task["id"], 1, current["transitions"])
    assert reserved["status"] == "in_progress" and reserved["result"] is None
    assert await worker.store.get_job(reserved["job_id"]) is None
    executor, schedule = await automation(system)
    result = await tick(executor, db)
    assert result["output"]["tasks"][0]["status"] == "CANCELLED"
    assert result["output"]["tasks"][0]["action"] == "reconciled"
    assert await worker.store.get_job(reserved["job_id"]) is None
    assert (await _call(db, "get_task", task["id"]))["transitions"] == reserved["transitions"]
    assert (await _call(db, "get_task", task["id"]))["result"]["status"] == "CANCELLED"
    assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 1
    retry = await client.post(f"/company/tasks/{task['id']}/runs", json={"attempt": 2})
    assert retry.status_code == 202, retry.text
    assert (await execute(worker))["status"] == "completed"


@pytest.mark.asyncio
async def test_automation_shutdown_records_cancellation_and_releases_claim(system, monkeypatch):
    from unittest.mock import AsyncMock

    from agno.company.execution import _call

    _, db, _, _, _ = system
    executor, schedule = await automation(system)
    monkeypatch.setattr(executor, "_tick", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await tick(executor, db)
    rows, total = await _call(db, "get_schedule_runs", schedule["id"])
    assert total == 1 and rows[0]["status"] == "cancelled"
    saved = await _call(db, "get_schedule", schedule["id"])
    assert saved["locked_by"] is None and saved["next_run_at"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("managed_by", ["studio", "other-control-plane"])
async def test_managed_schedule_patch_preserves_target(system, managed_by):
    from agno.company.execution import _call
    from agno.scheduler.manager import ScheduleManager

    client, db, _, _, _ = system
    schedule = await ScheduleManager(db).acreate(
        name="Managed target",
        cron="0 * * * *",
        endpoint="/agents/writer/runs",
        provenance={"managed_by": managed_by, "target_type": "agent", "target_id": "writer"},
    )
    response = await client.patch("/schedules/" + schedule.id, json={"endpoint": "/teams/editors/runs"})
    assert response.status_code == 200, response.text
    saved = await _call(db, "get_schedule", schedule.id)
    assert saved["endpoint"] == "/teams/editors/runs"
    assert (saved["target_type"], saved["target_id"]) == ("agent", "writer")
    assert saved["managed_by"] == managed_by


@pytest.mark.asyncio
@pytest.mark.parametrize("managed_by", [None, "company", "studio", "other-control-plane"])
@pytest.mark.parametrize("operation", ["update", "upsert"])
@pytest.mark.parametrize("async_api", [False, True])
async def test_python_schedule_retargeting_policy(system, managed_by, operation, async_api):
    from agno.company.execution import _call
    from agno.scheduler.manager import ScheduleManager

    _, db, _, _, _ = system
    manager = ScheduleManager(db)
    provenance = {"target_type": "agent", "target_id": "writer"}
    if managed_by is not None:
        provenance["managed_by"] = managed_by
    schedule = await manager.acreate(
        name="Python targets", cron="0 * * * *", endpoint="/agents/writer/runs", provenance=provenance
    )
    payload = {"message": "Keep the saved caller", "_agno_authorization": {"user_id": "original-caller"}}
    await _call(db, "update_schedule", schedule.id, payload=payload)

    async def change(endpoint):
        args = {"endpoint": endpoint}
        if operation == "upsert":
            method = "create"
            args.update(name=schedule.name, cron=schedule.cron_expr, if_exists="update")
        else:
            method = "update"
            args["schedule_id"] = schedule.id
        if async_api:
            return await getattr(manager, "a" + method)(**args)
        return await asyncio.to_thread(getattr(manager, method), **args)

    try:
        updated = await change("/teams/editors/runs/")
        expected = ("team", "editors") if managed_by in (None, "company") else ("agent", "writer")
        assert (updated.target_type, updated.target_id) == expected
        assert updated.managed_by == managed_by
        if operation == "update":
            assert updated.payload == payload
        if managed_by == "company":
            with pytest.raises(ValueError, match="Routine executor must be a run endpoint"):
                await change("/health")
            saved = await _call(db, "get_schedule", schedule.id)
            assert saved["endpoint"] == "/teams/editors/runs/"
        else:
            updated = await change("/health")
            expected = (None, None) if managed_by is None else ("agent", "writer")
            assert (updated.target_type, updated.target_id) == expected
    finally:
        manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["executor", "queue"])
async def test_automation_dispatch_failures_remain_visible(system, monkeypatch, failure):
    from unittest.mock import AsyncMock

    from agno.company.execution import _call

    client, db, worker, os, components = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    if failure == "executor":
        os.registry.agents.remove(components["writer"])
        reason = "Task executor is missing from the registry"
    else:
        reason = "queue storage unavailable"
        monkeypatch.setattr(worker.store, "get_job", AsyncMock(side_effect=RuntimeError(reason)))
    for _ in range(3):
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        result = await tick(executor, db)
        assert result["status"] == "failed", result
        assert reason in result["error"]
        assert result["output"]["tasks"][0]["status"] == "failed"
    rows, total = await _call(db, "get_schedule_runs", schedule["id"])
    assert total == 1 and reason in rows[0]["error"]
    assert rows[0]["output"]["automation_failure"]["count"] == 3
    assert (await _call(db, "get_task", task["id"]))["status"] == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["COMPLETED", "ERROR", "CANCELLED", "RUNNING", "PAUSED"])
@pytest.mark.parametrize("recovery", ["automation", "http"])
async def test_automation_reconciles_durable_run_without_resubmission(system, monkeypatch, status, recovery):
    from unittest.mock import AsyncMock

    from agno.company.execution import _call
    from agno.run import RunStatus

    client, db, worker, _, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    await tick(executor, db)
    reserved = await _call(db, "get_task", task["id"])
    # The model run commits, but projecting its result into the Task fails.
    with monkeypatch.context() as failure:

        def unavailable(*args, **kwargs):
            raise RuntimeError("Task result storage unavailable")

        failure.setattr(db, "complete_task_run", unavailable)
        await execute(worker)
    run = await _call(db, "get_run", reserved["job_id"])
    assert run.status == RunStatus.completed
    run.status = RunStatus(status)
    await _call(db, "upsert_run", run, session_id=task["session_id"])
    assert (await _call(db, "get_task", task["id"]))["result"] is None
    # Simulate a missing ticket, not normal retention of a running ticket.
    table = worker.config.db._get_table("jobs")
    with worker.config.db.Session() as session, session.begin():
        session.execute(table.delete().where(table.c.id == reserved["job_id"]))
    enqueue = AsyncMock(side_effect=AssertionError("An existing durable run must not be resubmitted"))
    monkeypatch.setattr(worker.store, "enqueue_job", enqueue)
    if recovery == "http":
        response = await client.post(f"/company/tasks/{task['id']}/runs")
        assert response.status_code == 202, response.text
        assert response.json()["status"] == status
    for index in range(3):
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        result = await tick(executor, db)
        assert result["status"] == "success", result
        if index == 0 and recovery == "automation":
            assert result["output"]["tasks"][0]["status"] == status
    enqueue.assert_not_called()
    saved = await _call(db, "get_task", task["id"])
    terminal = status in {"COMPLETED", "ERROR", "CANCELLED"}
    assert saved["status"] == ("in_review" if status == "COMPLETED" else "in_progress")
    assert saved["result"] == (
        {"run_id": run.run_id, "status": status, "content": run.content, "content_type": run.content_type}
        if terminal
        else None
    )
    assert await worker.store.get_job(reserved["job_id"]) is None
    assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == (
        2 if terminal and recovery == "automation" else 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["session", "run", "acceptance", "session_owner"])
async def test_terminal_reconciliation_preserves_task_and_session_guards(system, conflict):
    from fastapi import HTTPException

    from agno.company.execution import _call, _reconcile_task_run

    client, db, worker, _, _ = system
    task = await accepted(client)
    assert (await client.post(f"/company/tasks/{task['id']}/runs")).status_code == 202
    reserved = await _call(db, "get_task", task["id"])
    assert (await execute(worker))["status"] == "completed"
    run = await _call(db, "get_run", reserved["job_id"], deserialize=False)
    # A stale observation must not overwrite a later lifecycle transition.
    if conflict == "acceptance":
        await _call(db, "transition_task", task["id"], "in_progress", "Revise this result")
    elif conflict == "session":
        run["session_id"] = "another-session"
    elif conflict == "run":
        run["run_id"] = "another-run"
    else:
        from agno.db.base import SessionType

        session = await _call(db, "get_session", task["session_id"], session_type=SessionType.AGENT)
        session.user_id = "session-owner"
        await _call(db, "upsert_session", session)
    before = await _call(db, "get_task", task["id"])
    if conflict == "session_owner":
        with pytest.raises(HTTPException) as exc:
            await _reconcile_task_run(db, db, reserved, run, "another-user")
        assert exc.value.status_code == 404
    else:
        assert await _reconcile_task_run(db, db, reserved, run, None) is False
    assert await _call(db, "get_task", task["id"]) == before
