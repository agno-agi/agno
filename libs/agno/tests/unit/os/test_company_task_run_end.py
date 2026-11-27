"""A Task run that is lost with its worker is run again, and a Task whose run failed or was cancelled waits in review."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.schemas.tasks import task_run_id
from agno.db.sqlite import SqliteDb
from agno.job_queue import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, CompanyConfig
from agno.os.job_queue import QueueWorker
from agno.os.manager.company_tasks import CompanyTaskTools
from agno.os.manager.linked_work import _task_words
from agno.registry import Registry
from agno.run import RunContext


class CountingModel(Model):
    """Answer every request, or fail it, and count the requests."""

    def __init__(self):
        super().__init__(id="counting", provider="test")
        self.calls = 0
        self.down = False

    def invoke(self, *args, **kwargs):
        self.calls += 1
        if self.down:
            raise RuntimeError("The model is down")
        return ModelResponse(role="assistant", content="Draft written", response_usage=MessageMetrics())

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


class System:
    def __init__(self, tmp_path, **queue_options):
        self.db = SqliteDb(db_file=str(tmp_path / "company.db"))
        self.model = CountingModel()
        self.writer = Agent(id="writer", model=self.model, db=self.db, telemetry=False)
        self.os = AgentOS(
            id="company-task-run-end",
            db=self.db,
            agents=[self.writer],
            registry=Registry(agents=[self.writer]),
            company=CompanyConfig(),
            telemetry=False,
        )
        self.app = self.os.get_app()
        config = QueueConfig(durable=True, retry_delay_seconds=0, **queue_options)
        self.queue = QueueWorker(InMemoryQueueStore(), lambda *a, **k: self.writer, config, authorization_app=self.app)
        self.queue._company_db = self.db
        self.app.state.queue_worker = self.queue
        # The Company lifespan publishes the app to Super Agent tools; these tests drive it without a lifespan.
        self.os._company_app = self.app
        self.client = TestClient(self.app)

    def started(self):
        """A Task accepted for the writer, with its first run queued. Returns the Task and the run id."""
        goal = self.client.post("/company/goals", json={"name": "SDK"}).json()
        project = self.client.post("/company/projects", json={"goal_id": goal["id"], "name": "Release"}).json()
        self.client.post(
            f"/company/projects/{project['id']}/transitions", json={"target": "active", "reason": "Approved"}
        ).raise_for_status()
        task = self.client.post(
            "/company/tasks",
            json={"goal_id": goal["id"], "project_id": project["id"], "title": "Draft", "brief": "Write"},
        ).json()
        self.client.post(
            f"/company/tasks/{task['id']}/transitions",
            json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        ).raise_for_status()
        response = self.client.post(f"/company/tasks/{task['id']}/runs")
        assert response.status_code == 202, response.text
        return task, response.json()["run_id"]

    def ticket(self, run_id):
        return asyncio.run(self.queue.store.get_job(run_id))

    def claim(self):
        return asyncio.run(self.queue.store.claim_job(self.queue.worker_id, self.queue.config.lock_grace_seconds))

    def execute(self):
        """Claim the next ticket and execute it, as the worker's poll loop does. Returns the ticket after it."""

        async def run():
            job = await self.queue.store.claim_job(self.queue.worker_id, self.queue.config.lock_grace_seconds)
            assert job is not None
            await self.queue._execute_claimed(job)
            return await self.queue.store.get_job(job["id"])

        return asyncio.run(run())

    def lose_worker(self, run_id):
        """The worker holding the ticket is gone: its lease is no longer renewed, and the sweep finds it."""
        self.queue.store._jobs[run_id]["locked_at"] = 0
        asyncio.run(self.queue._sweep_exhausted())

    def task(self, task_id):
        return self.db.get_task(task_id)

    def start_from_chat(self, task_id):
        context = RunContext(run_id="chat-run", session_id="chat-session", user_id="alice")
        return asyncio.run(CompanyTaskTools(self.os).astart_company_task(task_id, _agno_run_context=context))

    def status_from_chat(self, task_id):
        context = RunContext(run_id="chat-run", session_id="chat-session", user_id="alice")
        tools = CompanyTaskTools(self.os)
        return json.loads(asyncio.run(tools.aget_company_task_status(task_id, _agno_run_context=context)))


@pytest.fixture
def system(tmp_path):
    value = System(tmp_path)
    yield value
    value.db.close()


# ----------------------------------------------------------------- a run lost with its worker


def test_a_task_ticket_may_be_executed_twice_and_another_run_once(system):
    _, run_id = system.started()
    ticket = system.ticket(run_id)
    # Two executions, the second only for a run whose worker was lost: a failed run keeps the queue's one.
    assert ticket["max_attempts"] == 2 and ticket["payload"]["max_failed_attempts"] == 1
    # A run of the same agent that is not a Task keeps the queue's own setting.
    plain = system.client.post(
        "/agents/writer/runs", data={"message": "Hello", "background": "true", "stream": "false"}
    )
    assert plain.status_code == 202, plain.text
    assert system.ticket(plain.json()["run_id"])["max_attempts"] == 1


def test_a_higher_queue_setting_applies_to_a_task_as_it_is(tmp_path):
    system = System(tmp_path, max_attempts=3)
    try:
        _, run_id = system.started()
        ticket = system.ticket(run_id)
        assert ticket["max_attempts"] == 3 and "max_failed_attempts" not in ticket["payload"]
        # The application's setting governs a failed run as it does for any other run: it is retried.
        system.model.down = True
        assert system.execute()["status"] == "queued"
    finally:
        system.db.close()


def test_a_task_run_lost_with_its_worker_is_run_again(system):
    task, run_id = system.started()
    # A worker claims the run and is lost before the run ends.
    assert system.claim()["attempt"] == 1
    system.lose_worker(run_id)
    # The sweep did not fail it: the ticket and the Task are as the lost worker left them.
    assert system.ticket(run_id)["status"] == "running"
    saved = system.task(task["id"])
    assert saved["status"] == "in_progress" and saved["result"] is None
    # The next worker executes it, under the same run id.
    after = system.execute()
    assert (after["id"], after["status"], after["attempt"]) == (run_id, "completed", 2)
    saved = system.task(task["id"])
    assert saved["status"] == "in_review" and saved["result"]["status"] == "COMPLETED"
    assert saved["result"]["content"] == "Draft written" and system.model.calls == 1


def test_a_task_run_lost_twice_is_failed_and_the_task_waits_in_review(system):
    task, run_id = system.started()
    assert system.claim()["attempt"] == 1
    system.lose_worker(run_id)
    assert system.claim()["attempt"] == 2
    system.lose_worker(run_id)
    assert system.ticket(run_id)["status"] == "failed" and system.claim() is None
    saved = system.task(task["id"])
    assert saved["status"] == "in_review" and saved["result"]["status"] == "ERROR"
    assert "Worker lost" in saved["result"]["content"] and system.model.calls == 0


def test_a_run_that_completed_before_its_ticket_was_settled_is_not_run_again(system, monkeypatch):
    task, run_id = system.started()
    with monkeypatch.context() as crash:
        # The server stops after the run is stored as completed and before its ticket is settled.
        async def never_settles(*args, **kwargs):
            return False

        crash.setattr(system.queue, "_asettle_ticket", never_settles)
        assert system.execute()["status"] == "running"
    assert system.model.calls == 1 and system.task(task["id"])["result"] is None
    system.lose_worker(run_id)
    # With attempts left the ticket is claimed again, and the claim settles it from the stored run.
    if system.ticket(run_id)["status"] == "running":
        system.execute()
    assert system.ticket(run_id)["status"] == "completed"
    saved = system.task(task["id"])
    assert saved["status"] == "in_review" and saved["result"]["status"] == "COMPLETED"
    assert system.model.calls == 1


# ----------------------------------------------------------------- a run that failed or was cancelled


def failed(system):
    """A Task whose run failed by itself. Returns the Task and the run id."""
    task, run_id = system.started()
    system.model.down = True
    # A run that fails by itself is executed once: the second execution is only for a lost worker.
    after = system.execute()
    assert (after["status"], after["attempt"]) == ("failed", 1) and system.model.calls == 1
    assert system.claim() is None
    system.model.down = False
    return task, run_id


def test_a_task_run_that_raises_is_executed_once(system, monkeypatch):
    task, run_id = system.started()
    calls = []

    async def raises(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("The executor raised")

    monkeypatch.setattr(system.writer, "arun", raises)
    after = system.execute()
    assert (after["status"], after["attempt"]) == ("failed", 1) and calls == [1]
    assert system.claim() is None
    saved = system.task(task["id"])
    assert saved["status"] == "in_review" and saved["result"]["status"] == "ERROR"
    assert "The executor raised" in saved["result"]["content"]


def test_a_run_that_failed_before_its_worker_was_lost_is_not_run_again(system, monkeypatch):
    task, run_id = system.started()
    system.model.down = True
    with monkeypatch.context() as crash:
        # The server stops after the run is stored as failed and before its ticket is settled.
        async def never_settles(*args, **kwargs):
            return None

        crash.setattr(system.queue, "_aretry_or_fail_ticket", never_settles)
        assert system.execute()["status"] == "running"
    system.model.down = False
    system.lose_worker(run_id)
    # The ticket is claimed again, and the claim fails it from the stored run without executing.
    after = system.execute()
    assert (after["status"], after["attempt"]) == ("failed", 2) and system.model.calls == 1
    saved = system.task(task["id"])
    assert saved["status"] == "in_review" and saved["result"]["status"] == "ERROR"


def test_a_task_whose_run_failed_waits_in_review_with_the_error(system):
    task, run_id = failed(system)
    saved = system.task(task["id"])
    assert saved["status"] == "in_review" and saved["job_id"] == run_id
    assert saved["result"]["status"] == "ERROR" and "The model is down" in saved["result"]["content"]
    step = saved["transitions"][-1]
    assert (step["from"], step["target"], step["ended_run"]) == ("in_progress", "in_review", run_id)
    assert step["reason"].startswith("Run failed")
    # It is listed and counted as failed, and its state is not worded as finished work.
    listed = system.client.get("/company/tasks", params={"failed": "true"}).json()["data"]
    assert [row["id"] for row in listed] == [task["id"]]
    assert system.client.get("/company/attention").json()["failed"] == 1
    state = system.status_from_chat(task["id"])
    assert (state["status"], state["run_status"]) == ("in_review", "ERROR")
    assert state["meaning"] == "its run failed or was cancelled, waiting for a person"
    assert _task_words(saved).startswith("started, its run ended in error, waiting for a person")


def test_a_person_retries_a_failed_task_in_review_from_chat(system):
    task, run_id = failed(system)
    reply = system.start_from_chat(task["id"])
    second = task_run_id(task["id"], 2)
    assert reply.startswith("Queued 'Draft'") and second in reply, reply
    retried = system.task(task["id"])
    assert (retried["status"], retried["job_id"], retried["result"]) == ("in_progress", second, None)
    assert system.execute()["status"] == "completed"
    saved = system.task(task["id"])
    assert saved["status"] == "in_review" and saved["result"]["status"] == "COMPLETED"
    assert system.client.get("/company/attention").json()["failed"] == 0
    # A Task whose run completed is still not started again from chat.
    assert "waiting for review" in system.start_from_chat(task["id"])


def test_naming_the_failed_attempt_joins_its_run_and_starts_nothing(system):
    task, run_id = failed(system)
    again = system.client.post(f"/company/tasks/{task['id']}/runs", json={"attempt": 1})
    assert again.status_code == 202, again.text
    assert again.json()["run_id"] == run_id and again.json()["status"] == "ERROR"
    assert system.task(task["id"])["status"] == "in_review" and system.claim() is None


def test_a_task_whose_run_was_cancelled_waits_in_review(system):
    task, run_id = system.started()
    cancelled = system.client.post(f"/company/runs/{run_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    saved = system.task(task["id"])
    assert saved["status"] == "in_review" and saved["result"]["status"] == "CANCELLED"
    assert saved["transitions"][-1]["reason"].startswith("Run cancelled")
    assert _task_words(saved).startswith("started, its run was cancelled, waiting for a person")
    assert system.start_from_chat(task["id"]).startswith("Queued 'Draft'")


def test_a_failed_task_stored_in_progress_is_still_listed_and_retried(system):
    task, run_id = failed(system)
    # A Task whose run failed before a run's end moved it to review: In progress, with the error as its result.
    table = system.db._get_table("tasks")
    saved = system.task(task["id"])
    with system.db.Session() as session, session.begin():
        session.execute(
            table.update()
            .where(table.c.id == task["id"])
            .values(status="in_progress", transitions=saved["transitions"][:-1])
        )
    listed = system.client.get("/company/tasks", params={"failed": "true"}).json()["data"]
    assert [row["id"] for row in listed] == [task["id"]]
    assert _task_words(system.task(task["id"])) == "started, its run ended in error"
    assert system.start_from_chat(task["id"]).startswith("Queued 'Draft'")
