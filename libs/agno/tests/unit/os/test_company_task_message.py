"""A person's message to a Task that has run: back to Ready and started again in one step, with no pause."""

import asyncio
import json

import pytest
from fastapi import HTTPException

from agno.company.execution import _automatic_task, _review_feedback, _task_input
from agno.company.manager import CompanyManager
from agno.db.schemas.scheduler import SCHEDULED_RUN_METADATA_KEY
from agno.db.schemas.tasks import task_run_id
from agno.os.manager import company_tasks
from agno.os.manager.company_tasks import CompanyTaskTools
from agno.os.manager.linked_work import _task_phase
from agno.os.manager.prompts import COMPANY_INSTRUCTIONS
from agno.os.routers.company.runs import _TaskStarter
from agno.registry._reserved import MINI_AGENT_ID
from agno.run import RunContext
from agno.run.authorization import AUTHORIZATION_KEY, authorization_scope
from tests.unit.os.test_company_decision_tools import (
    SCOPES,
    SECRET,
    automated_callers,
    build,
    call,
    chat,  # noqa: F401
    context,
    finish,
    headers,
    in_review,
    person,
    records,
    review,
    state,
    system,  # noqa: F401
    without_executor,
)
from tests.unit.os.test_super_agent_linked_work import ADD, CHANGED, linked, only_task, say, work

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

MESSAGE = "Add a short section on permissions"


@pytest.fixture(autouse=True)
def fresh_run_counts():
    company_tasks._accepted_in_run.clear()
    yield
    company_tasks._accepted_in_run.clear()


def message(agent_os, run_context, task_id, text=MESSAGE, **arguments):
    return call(agent_os, "message_company_task", run_context, task_id=task_id, message=text, **arguments)


def started(client, task_id):
    """Accept a Task for the writer and queue its first run."""
    accepted = client.post(
        f"/company/tasks/{task_id}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    )
    assert accepted.status_code == 200, accepted.text
    assert client.post(f"/company/tasks/{task_id}/runs", headers=headers()).status_code == 202


def ended(client, db, queue, task_id, how):
    """Start a Task and settle its run as failed or cancelled, as the queue worker does."""
    started(client, task_id)
    run_id = task_run_id(task_id, 1)

    async def settle():
        job = await queue.store.claim_job(queue.worker_id, queue.config.lock_grace_seconds)
        assert await queue.store.complete_job(run_id, queue.worker_id, job["attempt"], how)

    asyncio.run(settle())
    db.complete_task_run(
        task_id,
        run_id,
        {"run_id": run_id, "status": "ERROR" if how == "failed" else "CANCELLED", "content": "The model failed"},
        expected_transitions=db.get_task(task_id)["transitions"],
    )
    assert db.get_task(task_id)["status"] == "in_progress"


def fail(db, queue, task_id, attempt):
    """Settle the Task's queued run of this attempt as failed, as the queue worker does."""
    run_id = task_run_id(task_id, attempt)

    async def settle():
        job = await queue.store.claim_job(queue.worker_id, queue.config.lock_grace_seconds)
        assert job is not None and job["id"] == run_id
        assert await queue.store.complete_job(run_id, queue.worker_id, job["attempt"], "failed")

    asyncio.run(settle())
    db.complete_task_run(
        task_id,
        run_id,
        {"run_id": run_id, "status": "ERROR", "content": "The model failed"},
        expected_transitions=db.get_task(task_id)["transitions"],
    )


def sent_input(db, queue, task_id):
    """The queued run of the Task's latest attempt, and the input it was sent."""
    job = asyncio.run(queue.store.get_job(db.get_task(task_id)["job_id"]))
    return job, json.loads(job["payload"]["input"])


def jobs(queue):
    return sorted(queue.store._jobs)


# ----------------------------------------------------------------- what a message does


def test_a_message_to_a_task_in_review_starts_its_next_attempt_with_the_message(system):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    session = db.get_task(task["id"])["session_id"]

    reply = message(agent_os, context(), task["id"])
    second = task_run_id(task["id"], 2)
    # The receipt names the Task, the attempt and the run.
    assert reply.startswith("Sent the message to 'Draft' as attempt 2"), reply
    assert f"(Task {task['id']}, run {second})" in reply and "is not done" in reply

    saved = db.get_task(task["id"])
    returned, reserved = saved["transitions"][-2:]
    # The return to Ready is this person's act, with the message as its reason.
    assert (returned["from"], returned["target"], returned["reason"]) == ("in_review", "ready", MESSAGE)
    assert returned["user_id"] == "alice" and AUTHORIZATION_KEY in returned
    assert (saved["status"], saved["accepted_by"], saved["executor_id"]) == ("in_progress", "alice", "writer")
    assert reserved["attempt"] == 2 and reserved["requested_from"]["session_id"] == "chat-session"
    # The same session, the next attempt, and the message as a reply to the earlier result.
    job, sent = sent_input(db, queue, task["id"])
    assert job["id"] == second and job["session_id"] == session == saved["session_id"]
    assert sent["review_feedback"] == MESSAGE
    assert sent["previous_result"] == {"status": "COMPLETED", "content": "Draft written"}
    assert "act on review_feedback" in sent["execution_context"]["instructions"]
    assert set(sent) == {"brief", "evidence", "review_feedback", "previous_result", "execution_context"}


@pytest.mark.parametrize("how,status", [("failed", "ERROR"), ("cancelled", "CANCELLED")])
def test_a_message_to_a_task_whose_run_failed_or_was_cancelled_starts_its_next_attempt(system, how, status):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    ended(client, db, queue, task["id"], how)

    reply = message(agent_os, context(), task["id"])
    assert reply.startswith("Sent the message to 'Draft' as attempt 2"), reply
    saved = db.get_task(task["id"])
    returned = saved["transitions"][-2]
    assert (returned["from"], returned["target"], returned["reason"]) == ("in_progress", "ready", MESSAGE)
    job, sent = sent_input(db, queue, task["id"])
    assert job["id"] == task_run_id(task["id"], 2) and job["session_id"] == saved["session_id"]
    assert sent["review_feedback"] == MESSAGE
    assert sent["previous_result"] == {"status": status, "content": "The model failed"}


def test_a_return_from_a_failed_run_carries_its_reason_until_an_attempt_reaches_review():
    failed = {"status": "ERROR"}
    history = [
        {"from": "ready", "target": "in_progress", "attempt": 1},
        {"from": "in_progress", "target": "ready", "reason": "Use the other key"},
    ]
    assert _review_feedback({"transitions": history, "result": failed}) == "Use the other key"
    history += [{"from": "ready", "target": "in_progress", "attempt": 2}]
    assert _review_feedback({"transitions": history, "result": failed}) == "Use the other key"
    history += [{"from": "in_progress", "target": "in_review", "reason": "Execution completed"}]
    assert _review_feedback({"transitions": history, "result": {"status": "COMPLETED"}}) is None
    # A start is not a return.
    assert _review_feedback({"transitions": history[:1], "result": failed}) is None


def test_the_note_on_a_withdrawn_queued_attempt_is_not_a_reply(system):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    started(client, task["id"])
    moved = client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={"target": "ready", "reason": "Hold until Monday", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    )
    assert moved.status_code == 200, moved.text
    saved = db.get_task(task["id"])
    assert saved["result"] is None and _review_feedback(saved) is None
    sent = json.loads(asyncio.run(_task_input(CompanyManager(db, agent_os.registry), saved, accepted_execution=True)))
    assert "review_feedback" not in sent and "previous_result" not in sent


def test_a_reply_not_yet_acted_on_is_kept_beside_a_later_one(system):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    assert message(agent_os, context(), task["id"], text="Add a permissions section").startswith("Sent")
    fail(db, queue, task["id"], 2)
    assert message(agent_os, context(), task["id"], text="Try again, shorter").startswith("Sent")
    _, sent = sent_input(db, queue, task["id"])
    assert sent["review_feedback"] == "Add a permissions section\n\nTry again, shorter"
    # Once an attempt reaches review, the next reply stands alone.
    finish(db, queue, task["id"], attempt=3)
    assert _review_feedback(db.get_task(task["id"])) is None
    assert message(agent_os, context(), task["id"], text="Now add an example").startswith("Sent")
    assert sent_input(db, queue, task["id"])[1]["review_feedback"] == "Now add an example"


@pytest.mark.parametrize("origin", ["review", "failed"])
def test_a_return_to_backlog_ends_the_earlier_replies(system, origin):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    if origin == "review":
        in_review(client, db, queue, task["id"])
    else:
        ended(client, db, queue, task["id"], "failed")
    accept = {"target": "ready", "executor_type": "agent", "executor_id": "writer"}
    for body in (
        {**accept, "reason": "Use the old draft"},
        {"target": "backlog", "reason": "Rethink"},
        {**accept, "reason": "Approved"},
    ):
        client.post(f"/company/tasks/{task['id']}/transitions", json=body, headers=headers()).raise_for_status()
        if body["reason"] == "Use the old draft":
            assert _review_feedback(db.get_task(task["id"])) == "Use the old draft"
    assert _review_feedback(db.get_task(task["id"])) is None


def test_a_task_with_no_executor_goes_to_mini_agent(system):  # noqa: F811
    client, db, agent_os, queue = system
    task = without_executor(client, db, queue)
    before = state(db)
    # Mini Agent is the executor, so the person needs its run grant.
    without = context(scopes=[scope for scope in SCOPES if scope != f"agents:{MINI_AGENT_ID}:run"])
    assert message(agent_os, without, task["id"]).startswith("Not done")
    assert state(db) == before

    reply = message(agent_os, context(), task["id"])
    saved = db.get_task(task["id"])
    assert (saved["executor_type"], saved["executor_id"]) == ("agent", MINI_AGENT_ID), reply
    assert any(
        (entry.get("from"), entry.get("target"), entry.get("reason")) == ("in_review", "ready", MESSAGE)
        for entry in saved["transitions"]
    )


# ----------------------------------------------------------------- the stages it refuses


def staged(client, db, queue, stage):
    _, task = records(client)
    if stage == "ready":
        client.post(
            f"/company/tasks/{task['id']}/transitions",
            json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
            headers=headers(),
        ).raise_for_status()
    elif stage == "running":
        started(client, task["id"])
    elif stage in ("done", "cancelled"):
        in_review(client, db, queue, task["id"])
        client.post(
            f"/company/tasks/{task['id']}/transitions", json={"target": stage, "reason": "Closed"}, headers=headers()
        ).raise_for_status()
    return task


@pytest.mark.parametrize(
    "stage,sentence",
    [
        ("backlog", "Not sent: 'Draft' is a proposal that has not run. Edit its brief instead."),
        (
            "ready",
            "Not sent: 'Draft' is accepted and not started, so it has no result to answer. "
            "Edit its brief, or start it with start_company_task.",
        ),
        (
            "running",
            "Not sent: 'Draft' is still running. Nothing was interrupted and nothing is queued: "
            "the person asks again when its run has ended.",
        ),
        ("done", "Not sent: 'Draft' is done, and a message does not reopen a closed Task."),
        ("cancelled", "Not sent: 'Draft' is cancelled, and a message does not reopen a closed Task."),
    ],
)
def test_a_task_in_another_stage_is_refused_in_one_sentence_and_left_as_it_was(system, stage, sentence):  # noqa: F811
    client, db, agent_os, queue = system
    task = staged(client, db, queue, stage)
    before, queued = state(db), jobs(queue)
    assert message(agent_os, context(), task["id"]) == sentence
    assert state(db) == before and jobs(queue) == queued


def test_an_empty_message_and_an_unknown_task_send_nothing(system):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before = state(db)
    assert message(agent_os, context(), task["id"], text="  ") == "Not sent: the message is empty."
    assert message(agent_os, context(), "missing") == "Not sent: Task not found"
    assert state(db) == before


# ----------------------------------------------------------------- who may send one


@pytest.mark.parametrize("caller", ["routine-run", "task-run", "service-account", "scheduler", "automation-tick"])
def test_only_a_person_messages_a_task(system, caller):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before, queued = state(db), jobs(queue)
    token = _automatic_task.set({"id": "task"}) if caller == "automation-tick" else None
    try:
        reply = message(agent_os, automated_callers()[caller], task["id"])
    finally:
        if token is not None:
            _automatic_task.reset(token)
    assert reply.startswith("Not done") and "human" in reply, reply
    assert state(db) == before and jobs(queue) == queued


@pytest.mark.parametrize("mark", ["authority", "metadata"])
def test_a_scheduled_run_messages_no_task(system, mark):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before = state(db)
    caller = context()
    if mark == "authority":
        caller.authorization.scheduled = True
    else:
        caller.metadata = {SCHEDULED_RUN_METADATA_KEY: True}
    reply = message(agent_os, caller, task["id"])
    assert reply.startswith("Not done") and "no person present" in reply, reply
    assert state(db) == before


@pytest.mark.parametrize("authorization", [True, False], ids=["authorization-on", "authorization-off"])
def test_a_run_with_no_authority_messages_only_where_authorization_is_off(tmp_path, authorization):
    client, db, agent_os, queue = build(tmp_path, **({} if authorization else {"authorization": None}))
    try:
        _, task = records(client)
        in_review(client, db, queue, task["id"])
        before = state(db)
        nobody = RunContext(run_id="r", session_id="s", user_id=None, authorization=None)
        reply = message(agent_os, nobody, task["id"])
        if authorization:
            assert "signed-in person" in reply and state(db) == before, reply
        else:
            assert reply.startswith("Sent the message") and state(db) != before, reply
    finally:
        db.close()


def test_isolation_set_on_the_authorization_config_needs_a_signed_in_person(tmp_path):
    from agno.os.config import AuthorizationConfig

    config = AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256", user_isolation=True)
    client, db, agent_os, queue = build(tmp_path, authorization=True, authorization_config=config)
    try:
        _, task = records(client)
        in_review(client, db, queue, task["id"])
        before = state(db)
        assert "signed-in person" in message(agent_os, context(user=None), task["id"])
        assert state(db) == before
    finally:
        db.close()


@pytest.mark.parametrize("missing", ["tasks:write", "wiki:read", "agents:writer:run"])
def test_a_message_needs_the_grants_of_sending_back_and_starting(system, missing):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before, queued = state(db), jobs(queue)
    reply = message(agent_os, context(scopes=[scope for scope in SCOPES if scope != missing]), task["id"])
    assert reply.startswith("Not done"), reply
    assert state(db) == before and jobs(queue) == queued
    assert message(agent_os, context(), task["id"]).startswith("Sent the message")


def test_under_user_isolation_a_person_messages_only_their_own_task(system):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before = state(db)
    reply = message(agent_os, context(user="bob"), task["id"])
    if agent_os.user_isolation:
        assert reply == "Not sent: Task not found" and state(db) == before
        assert message(agent_os, context(), task["id"]).startswith("Sent the message")
    else:
        assert reply.startswith("Sent the message"), reply
        assert db.get_task(task["id"])["transitions"][-2]["user_id"] == "bob"


def test_an_executor_that_pushes_code_keeps_the_confirmed_path(system, monkeypatch):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before, queued = state(db), jobs(queue)
    monkeypatch.setattr("agno.company.sandbox._is_sandboxed", lambda component: True)
    reply = message(agent_os, context(), task["id"])
    assert reply.startswith("Not sent: agent writer runs in a sandbox") and "review_company_task" in reply, reply
    assert state(db) == before and jobs(queue) == queued


# ----------------------------------------------------------------- context sent with the message


def test_context_given_with_the_message_reaches_the_next_attempt(system):  # noqa: F811
    client, db, agent_os, queue = system
    _, earlier = records(client)
    in_review(client, db, queue, earlier["id"])
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    attached = [{"kind": "task", "ref": earlier["id"]}]

    reply = message(agent_os, context(), task["id"], context=attached)
    assert reply.startswith("Sent the message to 'Draft' as attempt 2"), reply
    saved = db.get_task(task["id"])
    assert [(entry["kind"], entry["ref"], entry["added_by"]) for entry in saved["context"]] == [
        ("task", earlier["id"], "alice")
    ]
    _, sent = sent_input(db, queue, task["id"])
    assert sent["review_feedback"] == MESSAGE and "context" in sent
    assert saved["transitions"][-1]["context_sent"]


@pytest.mark.parametrize(
    "refs,scopes,words",
    [
        ([{"kind": "task", "ref": "no-such-task"}], None, "Task not found"),
        ([{"kind": "file", "ref": "tasks/{task}/missing.md"}], None, "does not exist"),
        ([{"kind": "task", "ref": "{task}"}], [scope for scope in SCOPES if scope != "tasks:read"], "tasks:read"),
    ],
    ids=["missing-task", "missing-file", "unreadable"],
)
def test_refused_context_leaves_the_task_untouched(system, refs, scopes, words):  # noqa: F811
    client, db, agent_os, queue = system
    _, earlier = records(client)
    in_review(client, db, queue, earlier["id"])
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    refs = [{**ref, "ref": ref["ref"].replace("{task}", earlier["id"])} for ref in refs]
    before, queued = state(db), jobs(queue)
    stored = db.get_task(task["id"])
    reply = message(agent_os, context(scopes=scopes), task["id"], context=refs)
    assert reply.startswith("Not done") and words in reply, reply
    assert state(db) == before and jobs(queue) == queued
    assert db.get_task(task["id"]) == stored


# ----------------------------------------------------------------- a start that fails


@pytest.mark.parametrize("failure", [HTTPException(409, "The queue is full"), RuntimeError("The queue is down")])
def test_a_failed_start_leaves_the_task_ready_with_the_message_and_says_so(system, monkeypatch, failure):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    queued = jobs(queue)

    async def refuse(self, *args, **kwargs):
        raise failure

    with monkeypatch.context() as patched:
        patched.setattr(_TaskStarter, "submit", refuse)
        reply = message(agent_os, context(), task["id"])
    assert reply.startswith(f"The message is recorded on 'Draft' (Task {task['id']}), but its run did not start.")
    assert "The queue is" in reply and reply.endswith(
        "It is Ready: start it with start_company_task and the message goes with it."
    )
    assert not reply.startswith("Sent")
    saved = db.get_task(task["id"])
    assert saved["status"] == "ready" and saved["transitions"][-1]["reason"] == MESSAGE
    assert jobs(queue) == queued

    # A second message has no new result to answer; starting it sends the recorded message.
    assert message(agent_os, context(), task["id"], text="Again").startswith("Not sent: 'Draft' is accepted")
    assert "Queued" in call(agent_os, "start_company_task", context(), task_id=task["id"])
    assert sent_input(db, queue, task["id"])[1]["review_feedback"] == MESSAGE


def test_a_start_that_cannot_happen_is_refused_before_the_task_changes(system):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before = state(db)
    client.app.state.queue_worker = None
    try:
        reply = message(agent_os, context(), task["id"])
    finally:
        client.app.state.queue_worker = queue
    assert reply == "Not done: Company execution requires the durable queue"
    assert state(db) == before


def test_a_task_that_changes_while_the_message_is_sent_is_not_started(system, monkeypatch):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before, queued = state(db), jobs(queue)
    monkeypatch.setattr(type(_TaskStarter(agent_os).manager), "transition_task", lambda self, **fields: None)
    reply = message(agent_os, context(), task["id"])
    assert reply == "Not sent: 'Draft' changed while the message was being sent. Read it again."
    assert state(db) == before and jobs(queue) == queued


def test_a_retry_started_while_context_is_attached_is_not_returned_to_ready(system, monkeypatch):  # noqa: F811
    client, db, agent_os, queue = system
    _, earlier = records(client)
    in_review(client, db, queue, earlier["id"])
    _, task = records(client)
    ended(client, db, queue, task["id"], "failed")
    manager = type(_TaskStarter(agent_os).manager)
    attach = manager.change_task_context

    def racing(self, task_id, **fields):
        # Another caller retries the failed Task while this call attaches its context.
        assert client.post(f"/company/tasks/{task_id}/runs", headers=headers()).status_code == 202
        return attach(self, task_id, **fields)

    monkeypatch.setattr(manager, "change_task_context", racing)
    reply = message(agent_os, context(), task["id"], context=[{"kind": "task", "ref": earlier["id"]}])
    assert reply == (
        "Not sent: 'Draft' changed while the message was being sent. The context was attached. Read it again."
    )
    saved = db.get_task(task["id"])
    # The retry is still the Task's run, and the message is nowhere on its history.
    assert saved["status"] == "in_progress" and saved["job_id"] == task_run_id(task["id"], 2)
    assert saved["transitions"][-1]["attempt"] == 2
    assert all(entry.get("reason") != MESSAGE for entry in saved["transitions"])


def between_return_and_start(monkeypatch, act):
    """Run act once, right after the message returned the Task to Ready and before its start."""
    record_link = company_tasks.link_task

    def link(run_context, record, **options):
        if record.get("status") == "ready":
            act()
        return record_link(run_context, record, **options)

    monkeypatch.setattr(company_tasks, "link_task", link)


def test_a_task_closed_before_the_start_is_not_reported_as_sent(system, monkeypatch):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    queued = jobs(queue)

    def cancel():
        client.post(
            f"/company/tasks/{task['id']}/transitions", json={"target": "cancelled", "reason": "No"}, headers=headers()
        ).raise_for_status()

    between_return_and_start(monkeypatch, cancel)
    reply = message(agent_os, context(), task["id"])
    assert reply == (
        f"The message is recorded on 'Draft' (Task {task['id']}), but its run did not start. "
        "'Draft' is cancelled; only accepted work can start. It is now cancelled."
    )
    assert jobs(queue) == queued


def test_an_attempt_another_caller_started_and_lost_is_not_followed_by_an_extra_one(system, monkeypatch):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])

    def start_and_fail():
        from concurrent.futures import ThreadPoolExecutor

        assert client.post(f"/company/tasks/{task['id']}/runs", headers=headers()).status_code == 202
        # The message tool's event loop is running here, and settling a run starts one of its own.
        with ThreadPoolExecutor(1) as pool:
            pool.submit(fail, db, queue, task["id"], 2).result()

    between_return_and_start(monkeypatch, start_and_fail)
    reply = message(agent_os, context(), task["id"])
    second = task_run_id(task["id"], 2)
    # Attempt 2 carried the message. The receipt names it and how it stands; no attempt 3 is queued.
    assert reply.startswith("Sent the message to 'Draft' as attempt 2") and f"run {second})" in reply, reply
    assert "already has this attempt" in reply
    saved = db.get_task(task["id"])
    assert saved["job_id"] == second and task_run_id(task["id"], 3) not in jobs(queue)
    assert sent_input(db, queue, task["id"])[1]["review_feedback"] == MESSAGE


def accepted_by_policy(db, task_id):
    """Mark the Task's acceptance as a Routine policy's, as an automatic acceptance records it."""
    from sqlalchemy import update

    saved = db.get_task(task_id)
    next(entry for entry in saved["transitions"] if entry.get("target") == "ready")["auto_accept"] = {
        "routine_id": "routine",
        "policy": "policy",
    }
    table = db._get_table(table_type="tasks")
    with db.Session() as sess, sess.begin():
        sess.execute(update(table).where(table.c.id == task_id).values(transitions=saved["transitions"]))


@pytest.mark.parametrize("stage", ["review", "failed"])
def test_a_task_a_policy_accepted_keeps_the_confirmed_path(system, stage):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    if stage == "review":
        in_review(client, db, queue, task["id"])
    else:
        ended(client, db, queue, task["id"], "failed")
    accepted_by_policy(db, task["id"])
    before, queued = state(db), jobs(queue)
    reply = message(agent_os, context(), task["id"])
    assert reply.startswith("Not sent: a Routine's policy accepted 'Draft'"), reply
    assert ("review_company_task" in reply) is (stage == "review")
    assert state(db) == before and jobs(queue) == queued
    # A person who sent it back themselves has accepted it, and may message it from then on.
    if stage == "review":
        assert review(agent_os, context(), task, "send_back", "Redo").startswith("Sent 'Draft'")
        assert "Queued" in call(agent_os, "start_company_task", context(), task_id=task["id"])
        finish(db, queue, task["id"], attempt=2)
        assert message(agent_os, context(), task["id"]).startswith("Sent the message to 'Draft' as attempt 3")


# ----------------------------------------------------------------- no pause, and the sync tool


def test_the_tool_does_not_pause_or_end_the_turn_and_review_still_pauses(system):  # noqa: F811
    client, db, agent_os, queue = system
    tools = CompanyTaskTools(agent_os)
    for functions in (tools.get_functions(), tools.get_async_functions()):
        function = functions["message_company_task"]
        assert not function.requires_confirmation and not function.stop_after_tool_call
        assert functions["review_company_task"].requires_confirmation is True
    described = tools.get_async_functions()["message_company_task"]
    assert "CONTEXT_KINDS" not in (described.entrypoint.__doc__ or "")


def test_the_sync_tool_sends_nothing(system):  # noqa: F811
    client, db, agent_os, queue = system
    _, task = records(client)
    in_review(client, db, queue, task["id"])
    before, queued = state(db), jobs(queue)
    reply = CompanyTaskTools(agent_os).message_company_task(task["id"], MESSAGE, _agno_run_context=context())
    assert reply == "Messaging a Task needs an asynchronous run. Send the Task back from AgentOS instead."
    assert state(db) == before and jobs(queue) == queued


def test_the_prompt_names_the_message_tool_for_a_reply_and_review_for_completing():
    assert "then start it with start_company_task" not in COMPANY_INSTRUCTIONS
    bullet = next(part for part in COMPANY_INSTRUCTIONS.split("\n- ") if "message_company_task" in part)
    assert "answers a finished Task's question" in bullet and "no confirmation" in bullet
    assert "Completing a Task still goes through review_company_task" in " ".join(bullet.split())


# ----------------------------------------------------------------- in a Super Agent conversation


def task_line(sent, task_id):
    return next(line for line in sent.splitlines() if task_id in line)


def test_a_message_in_chat_does_not_pause_and_is_not_reported_back_as_a_change(chat):  # noqa: F811
    say(chat, [("add_company_task", {**ADD, "start": True})])
    task = only_task(chat)
    work(chat)
    _, sent = say(chat)
    assert CHANGED in task_line(sent, task["id"])

    run, _ = say(chat, [("message_company_task", {"task_id": task["id"], "message": MESSAGE})])
    assert not run.is_paused and not (run.requirements or [])
    tool = next(item for item in run.tools if item.tool_name == "message_company_task")
    assert tool.result.startswith("Sent the message to 'Draft the notes' as attempt 2"), tool.result
    # The turn went on after the call: the model was asked again and answered.
    assert run.content
    saved = chat.db.get_task(task["id"])
    assert saved["status"] == "in_progress" and saved["transitions"][-1]["attempt"] == 2
    entry = next(item for item in linked(chat) if item["id"] == task["id"])
    assert entry["shown"] == _task_phase(saved) and entry["changed_in"] != run.run_id

    # The next message shows it started, without the mark: this conversation started it.
    _, sent = say(chat)
    line = task_line(sent, task["id"])
    assert "started" in line and CHANGED not in line
    # When the second attempt ends, that is news.
    work(chat)
    _, sent = say(chat)
    assert "finished, waiting for review" in task_line(sent, task["id"]) and CHANGED in task_line(sent, task["id"])


def test_a_message_to_a_task_from_elsewhere_adds_it_to_the_conversation(chat):  # noqa: F811
    task = chat.proposal()
    chat.accept(task["id"])
    chat.execute(task["id"])
    run, _ = say(chat, [("message_company_task", {"task_id": task["id"], "message": MESSAGE})])
    saved = chat.db.get_task(task["id"])
    assert saved["transitions"][-1]["attempt"] == 2
    assert [(item["id"], item["shown"]) for item in linked(chat)] == [(task["id"], _task_phase(saved))]
    _, sent = say(chat)
    assert CHANGED not in task_line(sent, task["id"])


def test_a_refused_message_in_chat_changes_nothing_and_lists_nothing(chat):  # noqa: F811
    task = chat.proposal()
    chat.accept(task["id"])
    with authorization_scope(person):
        started_first = chat.client.post(f"/company/tasks/{task['id']}/runs", headers=_chat_headers())
    assert started_first.status_code == 202
    before = chat.db.get_task(task["id"])
    run, _ = say(chat, [("message_company_task", {"task_id": task["id"], "message": MESSAGE})])
    tool = next(item for item in run.tools if item.tool_name == "message_company_task")
    assert tool.result.startswith("Not sent: ") and "is still running" in tool.result
    assert chat.db.get_task(task["id"]) == before and linked(chat) == []


def _chat_headers():
    from tests.unit.os.test_mini_agent_tasks import headers as chat_headers

    return chat_headers()
