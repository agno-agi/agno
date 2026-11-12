"""Super Agent in Slack: Task results derived from stored rows and posted once into the thread that started them."""

import asyncio
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from slack_sdk.errors import SlackApiError

from agno.agent import Agent
from agno.db.schemas.tasks import task_run_id
from agno.db.sqlite import SqliteDb
from agno.models.response import ToolExecution
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.os.interfaces.slack import company as company_module
from agno.os.interfaces.slack.company import _RESULT_EVENT, CompanyBridge, TaskDelivery
from agno.os.interfaces.slack.helpers import LookupCache
from agno.registry import Registry
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team import Team

SECRET = "slack-company-tests-secret-at-least-32-bytes"
ENTITY_ID = "superagent"
THREAD = "1708123456.000100"
SESSION_ID = f"{ENTITY_ID}:C123:{THREAD}"


class FakeSlack:
    """A Slack thread: replies page 100 at a time, and posted messages join the thread with their metadata."""

    def __init__(self, root_user: str = "U_ALICE", replies: Optional[List[Dict[str, Any]]] = None):
        self.root: Dict[str, Any] = {"user": root_user, "ts": THREAD}
        self.thread: List[Dict[str, Any]] = list(replies or [])
        self.emails: Dict[str, str] = {}
        self.chat_postMessage = AsyncMock(side_effect=self._post)
        self.conversations_replies = AsyncMock(side_effect=self._replies)
        self.users_info = AsyncMock(side_effect=self._users_info)

    async def _post(self, **kwargs: Any) -> Dict[str, Any]:
        self.thread.append({"bot_id": "B1", "text": kwargs["text"], "metadata": kwargs.get("metadata")})
        return {"ok": True}

    async def _replies(self, channel: str, ts: str, cursor: Optional[str] = None, **kwargs: Any):
        if kwargs.get("latest"):
            # One message by its ts; Slack returns the root alongside it.
            found = [m for m in self.thread if m.get("ts") == kwargs["latest"]]
            return {"messages": [self.root, *found], "response_metadata": {"next_cursor": ""}}
        page = int(cursor or 0)
        more = (page + 1) * 100 < len(self.thread)
        return {
            "messages": self.thread[page * 100 : (page + 1) * 100],
            "response_metadata": {"next_cursor": str(page + 1) if more else ""},
        }

    async def _users_info(self, user: str) -> Dict[str, Any]:
        return {"user": {"profile": {"email": self.emails.get(user)}}}

    def posted(self) -> List[Dict[str, Any]]:
        return [call.kwargs for call in self.chat_postMessage.await_args_list]

    def marker_reads(self) -> List[Dict[str, Any]]:
        calls = self.conversations_replies.await_args_list
        return [call.kwargs for call in calls if call.kwargs.get("include_all_metadata")]


def _seed_task(db_file: str) -> Dict[str, Any]:
    """An accepted Task, made through the Company routes of an AgentOS without authorization."""
    db = SqliteDb(db_file=db_file)
    agent_os = AgentOS(
        id="seed",
        db=db,
        registry=Registry(agents=[Agent(id="writer", db=db)]),
        company=CompanyConfig(),
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())
    product = client.post("/company/products", json={"name": "SDK"}).json()
    project = client.post("/company/projects", json={"product_id": product["id"], "name": "Release"}).json()
    client.post(f"/company/projects/{project['id']}/transitions", json={"target": "active", "reason": "Approved"})
    task = client.post(
        "/company/tasks",
        json={"product_id": product["id"], "project_id": project["id"], "title": "Investigate", "brief": "Find why"},
    ).json()
    client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
    ).raise_for_status()
    return db.get_task(task["id"])


def _finish_attempt(db: SqliteDb, task: Dict[str, Any], run_id: str, user_id: str, session_id: str = SESSION_ID):
    """The attempt Super Agent's turn started, then its run's saved result."""
    _start_attempt(db, task, run_id, user_id, session_id)
    _complete_attempt(db, task)


def _start_attempt(db: SqliteDb, task: Dict[str, Any], run_id: str, user_id: str, session_id: str = SESSION_ID):
    db.start_task_run(
        task["id"],
        1,
        expected_transitions=task["transitions"],
        user_id=user_id,
        requested_from={"session_id": session_id, "run_id": run_id, "team_id": ENTITY_ID},
    )


def _complete_attempt(db: SqliteDb, task: Dict[str, Any]) -> None:
    job_id = task_run_id(task["id"], 1)
    db.complete_task_run(
        task["id"],
        job_id,
        {"run_id": job_id, "status": "COMPLETED", "content": "Found it: the old IAM role."},
        expected_transitions=db.get_task(task["id"])["transitions"],
    )


def _save_turn(
    db: SqliteDb,
    task_id: str,
    run_id: str,
    user_id: str,
    session_id: str = SESSION_ID,
    session_owner: Optional[str] = None,
    tool_name: str = "start_company_task",
    tool_call_error: bool = False,
    message_ts: Optional[str] = THREAD,
) -> None:
    """The Super Agent turn as its session stores it: the run and its start_company_task call."""
    receipt = f"Queued 'Investigate' (Task {task_id}, run {task_run_id(task_id, 1)}). It runs in its own session."
    tool = ToolExecution(
        tool_name=tool_name, tool_args={"task_id": task_id}, result=receipt, tool_call_error=tool_call_error
    )
    run = TeamRunOutput(
        run_id=run_id,
        session_id=session_id,
        team_id=ENTITY_ID,
        user_id=user_id,
        tools=[tool],
        status=RunStatus.completed,
        metadata={"slack_message_ts": message_ts} if message_ts else None,
    )
    owner = session_owner or user_id
    db.upsert_session(TeamSession(session_id=session_id, team_id=ENTITY_ID, user_id=owner, session_data={}))
    db.upsert_run(run, session_id=session_id, user_id=user_id)


@pytest.fixture
def company(tmp_path):
    """A Company with one Task finished from a Slack thread, served by an AgentOS without authorization."""
    db_file = str(tmp_path / "company.db")
    task = _seed_task(db_file)
    db = SqliteDb(db_file=db_file)
    agent_os = _company_os(db)
    _finish_attempt(db, task, "slack-run", "U_ALICE")
    _save_turn(db, task["id"], "slack-run", "U_ALICE")
    yield db, agent_os, task
    db.close()


def _company_os(db: SqliteDb, authorization: Any = None) -> AgentOS:
    agent_os = AgentOS(
        id="slack-company",
        db=db,
        registry=Registry(agents=[Agent(id="writer", db=db)]),
        company=CompanyConfig(),
        authorization=authorization,
        telemetry=False,
    )
    agent_os._company_app = agent_os.get_app()
    return agent_os


def _delivery(
    agent_os: AgentOS,
    db: SqliteDb,
    slack: FakeSlack,
    users: Optional[Dict[str, str]] = None,
    resolve_user_identity: bool = False,
):
    ctx = SimpleNamespace(
        company=CompanyBridge(agent_os),
        entity=Team(id=ENTITY_ID, members=[], db=db),
        entity_id=ENTITY_ID,
        users=users,
        resolve_user_identity=resolve_user_identity,
        web=lambda: slack,
        lookup_cache=LookupCache(),
        runs=SimpleNamespace(spawn=asyncio.ensure_future),
        markdown=True,
        unfurl_links=True,
        unfurl_media=True,
    )
    return TaskDelivery(ctx)


# ---------------------------------------------------------------------------
# What is posted
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_posts_result_once_to_thread(company):
    db, agent_os, task = company
    before = db.get_session(SESSION_ID, None, deserialize=False)["session_data"]
    slack = FakeSlack()
    delivery = _delivery(agent_os, db, slack)
    await delivery.sweep()
    await delivery.sweep()

    [post] = slack.posted()
    assert post["channel"] == "C123" and post["thread_ts"] == THREAD
    assert post["metadata"] == {"event_type": _RESULT_EVENT, "event_payload": {"task_id": task["id"], "attempt": 1}}
    assert post["text"].startswith(f"'Investigate' (Task {task['id']}, attempt 1): finished, waiting for review")
    assert "Found it: the old IAM role." in post["text"]
    # The marker read starts at the attempt, so a long thread does not hide it.
    attempt_start = db.get_task(task["id"])["transitions"][-1]["created_at"]
    assert slack.marker_reads()[0]["oldest"] == str(attempt_start)
    assert db.get_session(SESSION_ID, None, deserialize=False)["session_data"] == before


@pytest.mark.parametrize(
    "turn",
    [
        {"tool_name": "get_company_task_status"},
        {"tool_call_error": True},
        {"message_ts": None},
        {"session_id": f"other-agent:C123:{THREAD}"},
        {"session_id": f"{ENTITY_ID}:{THREAD}"},
    ],
    ids=["no-start-call", "failed-start-call", "no-slack-message", "other-entity", "legacy-session"],
)
@pytest.mark.asyncio
async def test_sweep_skips_task_not_started_here(tmp_path, turn):
    db_file = str(tmp_path / "company.db")
    task = _seed_task(db_file)
    db = SqliteDb(db_file=db_file)
    session_id = turn.pop("session_id", SESSION_ID)
    _finish_attempt(db, task, "slack-run", "U_ALICE", session_id=session_id)
    _save_turn(db, task["id"], "slack-run", "U_ALICE", session_id=session_id, **turn)
    slack = FakeSlack()
    await _delivery(_company_os(db), db, slack).sweep()
    assert slack.posted() == []


# ---------------------------------------------------------------------------
# Delivered marker and retries
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sweep_retries_failed_post_once(company, monkeypatch):
    monkeypatch.setattr(company_module, "_RETRY_MIN", 0.0)
    # The sweeps run two minutes after the Task finished, so only a held mark covers it again.
    later = time.time() + 120
    monkeypatch.setattr(company_module, "time", SimpleNamespace(time=lambda: later, monotonic=time.monotonic))
    db, agent_os, task = company
    slack = FakeSlack()
    slack.chat_postMessage.side_effect = [
        SlackApiError("ratelimited", {"ok": False, "error": "ratelimited"}),
        {"ok": True},
    ]
    delivery = _delivery(agent_os, db, slack)

    await delivery.sweep()
    # The mark holds at the failed Task, so the next sweep covers it again.
    assert delivery._mark <= db.get_task(task["id"])["updated_at"]
    await delivery.sweep()
    await delivery.sweep()
    assert slack.chat_postMessage.await_count == 2
    assert delivery._retry == {}


@pytest.mark.asyncio
async def test_marker_found_on_third_page(company):
    db, agent_os, task = company
    replies: List[Dict[str, Any]] = [{"user": "U_ALICE", "text": f"reply {n}"} for n in range(300)]
    replies[250]["metadata"] = {"event_type": _RESULT_EVENT, "event_payload": {"task_id": task["id"], "attempt": 1}}
    slack = FakeSlack(replies=replies)
    await _delivery(agent_os, db, slack).sweep()

    assert slack.posted() == []
    reads = slack.marker_reads()
    assert [read.get("cursor") for read in reads] == [None, "1", "2"]
    assert all(read["oldest"] and read["include_all_metadata"] for read in reads)


@pytest.mark.asyncio
async def test_failed_history_read_is_retried_not_posted(company, monkeypatch):
    db, agent_os, task = company
    warnings: List[str] = []
    monkeypatch.setattr(company_module, "log_warning", warnings.append)
    slack = FakeSlack()
    slack.conversations_replies.side_effect = SlackApiError("missing_scope", {"ok": False, "error": "missing_scope"})
    delivery = _delivery(agent_os, db, slack)
    await delivery.sweep()

    assert slack.posted() == []
    assert len(warnings) == 1 and task["id"] in warnings[0] and "missing_scope" in warnings[0]
    assert (task["id"], 1) in delivery._retry


@pytest.mark.asyncio
async def test_restart_backfills_unposted_result(company):
    db, agent_os, task = company
    slack = FakeSlack()
    slack.chat_postMessage.side_effect = SlackApiError("fatal_error", {"ok": False, "error": "fatal_error"})
    # The first process fails to post, then stops with the Task in its in-memory retry set.
    await _delivery(agent_os, db, slack).sweep()
    slack.chat_postMessage.side_effect = slack._post

    await _delivery(agent_os, db, slack).sweep()
    # A third start finds the marker in the thread.
    await _delivery(agent_os, db, slack).sweep()
    assert len(slack.posted()) == 2 and len([m for m in slack.thread if m.get("metadata")]) == 1


@pytest.mark.asyncio
async def test_session_save_after_post_does_not_repost(company):
    db, agent_os, task = company
    slack = FakeSlack()

    async def post_while_a_turn_saves(**kwargs: Any) -> Dict[str, Any]:
        # A concurrent turn rewrites the whole session row between the post and any later sweep.
        _save_turn(db, task["id"], "slack-run", "U_ALICE")
        return await slack._post(**kwargs)

    slack.chat_postMessage.side_effect = post_while_a_turn_saves
    await _delivery(agent_os, db, slack).sweep()
    slack.chat_postMessage.side_effect = slack._post
    # A new process (no in-memory record) finds the marker in Slack and posts nothing.
    await _delivery(agent_os, db, slack).sweep()
    assert slack.chat_postMessage.await_count == 1


@pytest.mark.asyncio
async def test_sweep_posts_result_committed_late(tmp_path, monkeypatch):
    db_file = str(tmp_path / "company.db")
    task = _seed_task(db_file)
    db = SqliteDb(db_file=db_file)
    _start_attempt(db, task, "slack-run", "U_ALICE")
    _save_turn(db, task["id"], "slack-run", "U_ALICE")
    # The sweeps run a few seconds ahead of the database clock.
    ahead = time.time() + 5
    monkeypatch.setattr(company_module, "time", SimpleNamespace(time=lambda: ahead, monotonic=time.monotonic))
    slack = FakeSlack()
    delivery = _delivery(_company_os(db), db, slack)
    await delivery.sweep()
    # The result lands with an updated_at before the first sweep started, and is first seen on the second.
    _complete_attempt(db, db.get_task(task["id"]))
    assert db.get_task(task["id"])["updated_at"] < int(ahead)
    await delivery.sweep()
    assert len(slack.posted()) == 1


@pytest.mark.asyncio
async def test_sweep_skips_tasks_before_mark(company):
    db, agent_os, task = company
    slack = FakeSlack()
    delivery = _delivery(agent_os, db, slack)
    delivery._mark = int(time.time()) + 60
    await delivery.sweep()
    assert slack.conversations_replies.await_count == 0 and slack.posted() == []


# ---------------------------------------------------------------------------
# Participants: the run's user wrote the Slack message that started the run, in that thread
# ---------------------------------------------------------------------------
def _authorized_company(tmp_path, run_user: str, message_ts: str = THREAD, session_owner: Optional[str] = None):
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256")
    auth.define_role("asker", ["teams:run", "tasks:read"])
    auth.define_role("runner", ["teams:run"])
    auth.assign("alice", "asker").assign("bob", "asker").assign("carol", "runner")
    db_file = str(tmp_path / "company.db")
    task = _seed_task(db_file)
    db = SqliteDb(db_file=db_file)
    agent_os = _company_os(db, authorization=auth)
    _finish_attempt(db, task, "run-1", run_user)
    _save_turn(db, task["id"], "run-1", run_user, message_ts=message_ts, session_owner=session_owner)
    return db, agent_os


USERS = {"U_ALICE": "alice", "U_BOB": "bob", "U_CAROL": "carol"}
BOB_REPLY = "1708123456.000200"


@pytest.mark.parametrize(
    "run_user, message_ts, root_user, posted",
    [
        # The root message itself: a DM or a new thread, message_ts == thread_ts.
        ("alice", THREAD, "U_ALICE", True),
        # Bob's reply under Alice's root, in the session Alice's first message created.
        ("bob", BOB_REPLY, "U_ALICE", True),
        # Bob's run naming Alice's message: a message by another user.
        ("bob", THREAD, "U_ALICE", False),
        # Forged metadata: no such message in the thread.
        ("bob", "1708123456.000999", "U_ALICE", False),
        # Carol wrote the message but can no longer read Tasks.
        ("carol", THREAD, "U_CAROL", False),
    ],
    ids=["root-message", "reply-under-others-root", "other-users-message", "no-such-message", "access-revoked"],
)
@pytest.mark.asyncio
async def test_authorization_posts_only_message_authors_task(tmp_path, run_user, message_ts, root_user, posted):
    db, agent_os = _authorized_company(tmp_path, run_user, message_ts, session_owner="alice")
    slack = FakeSlack(root_user=root_user, replies=[{"user": "U_BOB", "ts": BOB_REPLY}])
    await _delivery(agent_os, db, slack, users=USERS).sweep()
    assert bool(slack.posted()) is posted


# A user-token post carries both the human's user id and the app's bot id
@pytest.mark.parametrize("bot_id", [None, "B_APP"], ids=["user-post", "user-token-post"])
@pytest.mark.asyncio
async def test_email_identity_gets_result(tmp_path, bot_id):
    db_file = str(tmp_path / "company.db")
    task = _seed_task(db_file)
    db = SqliteDb(db_file=db_file)
    _finish_attempt(db, task, "slack-run", "alice@example.com")
    _save_turn(db, task["id"], "slack-run", "alice@example.com")
    slack = FakeSlack(root_user="U_ALICE")
    slack.root["bot_id"] = bot_id
    slack.emails["U_ALICE"] = "alice@example.com"
    await _delivery(_company_os(db), db, slack, resolve_user_identity=True).sweep()
    assert len(slack.posted()) == 1


BOT_MESSAGE = "1708123456.000300"


@pytest.mark.parametrize(
    "run_user, message_ts, lookup, found",
    [
        ("alice@example.com", THREAD, "users_info", {"user": {"profile": {"email": "alice@example.com"}}}),
        ("B_HOOK", BOT_MESSAGE, "bots_info", {"bot": {"name": "Deploy hook"}}),
    ],
    ids=["user", "bot"],
)
@pytest.mark.asyncio
async def test_failed_identity_lookup_is_retried(tmp_path, monkeypatch, run_user, message_ts, lookup, found):
    monkeypatch.setattr(company_module, "_RETRY_MIN", 0.0)
    db_file = str(tmp_path / "company.db")
    task = _seed_task(db_file)
    db = SqliteDb(db_file=db_file)
    _finish_attempt(db, task, "slack-run", run_user)
    _save_turn(db, task["id"], "slack-run", run_user, message_ts=message_ts)
    slack = FakeSlack(root_user="U_ALICE", replies=[{"bot_id": "B_HOOK", "ts": BOT_MESSAGE}])
    setattr(
        slack,
        lookup,
        AsyncMock(side_effect=[SlackApiError("ratelimited", {"ok": False, "error": "ratelimited"}), found]),
    )
    delivery = _delivery(_company_os(db), db, slack, resolve_user_identity=True)

    await delivery.sweep()
    assert slack.posted() == [] and (task["id"], 1) in delivery._retry
    await delivery.sweep()
    assert len(slack.posted()) == 1 and delivery._retry == {}


@pytest.mark.asyncio
async def test_authorization_off_trusts_caller_user_id(tmp_path):
    # Documented limit: without authorization a run's user_id is caller-supplied, so a REST caller
    # naming Alice's principal and thread gets its Task result posted there.
    db_file = str(tmp_path / "company.db")
    task = _seed_task(db_file)
    db = SqliteDb(db_file=db_file)
    _finish_attempt(db, task, "rest-run", "alice")
    _save_turn(db, task["id"], "rest-run", "alice")
    slack = FakeSlack(root_user="U_ALICE")
    await _delivery(_company_os(db), db, slack, users=USERS).sweep()
    assert len(slack.posted()) == 1


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_spawns_and_loop_survives_failing_sweep(company, monkeypatch):
    db, agent_os, task = company
    monkeypatch.setattr(company_module, "_SWEEP_SECONDS", 0.01)
    delivery = _delivery(agent_os, db, FakeSlack())
    sweeps: List[int] = []

    async def failing_sweep() -> None:
        sweeps.append(1)
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(delivery, "sweep", failing_sweep)
    await delivery.start()
    assert sweeps == []
    while len(sweeps) < 2:
        await asyncio.sleep(0.01)
    task_handle = delivery._task
    await delivery.stop()
    assert task_handle is not None and task_handle.cancelled()
