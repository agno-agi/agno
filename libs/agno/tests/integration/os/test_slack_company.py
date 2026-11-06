"""Offline Slack transport with real PostgreSQL receipts, queue and API calls."""

import asyncio
import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, Authorization, CompanyConfig, OSManager
from agno.os.interfaces.slack import Slack, SlackCompany
from agno.os.interfaces.slack.company import _identity
from agno.os.interfaces.slack.store import _SlackStore

URL = "postgresql+psycopg://agno:agno@127.0.0.1:5532/agno"
SECRET = "offline-slack-signature-secret"


class OfflineModel(Model):
    def __init__(self):
        super().__init__(id="fixture", provider="test")
        self.calls = 0
        self.next_tool = None

    def invoke(self, *args, **kwargs):
        self.calls += 1
        if self.next_tool:
            tool = self.next_tool
            self.next_tool = None
            return ModelResponse(
                role="assistant",
                tool_calls=[{"id": "offline-tool", "type": "function", "function": {"name": tool, "arguments": "{}"}}],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(content="Offline response", role="assistant", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs):
        return self.invoke()

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke()

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.fixture
def database():
    schema = "slack_company_" + uuid4().hex[:12]
    db = PostgresDb(db_url=URL, db_schema=schema)
    with db.db_engine.begin() as conn:
        conn.execute(text('CREATE SCHEMA "' + schema + '"'))
    yield db
    with db.db_engine.begin() as conn:
        conn.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
    db.close()


@pytest.mark.asyncio
async def test_receipts_and_delivery_leases_survive_restart(database):
    first = _SlackStore(database, "workspace-a")
    await first._initialize()
    values = {
        "channel": "C1",
        "thread": "1",
        "message": "work",
        "run_id": "run",
        "notifications": {"result": {"text": "done", "sent": False}},
    }
    rows = await asyncio.gather(*[first._receive("event", "conversation", "alice", values) for _ in range(4)])
    assert len({row["id"] for row in rows}) == 1
    second = _SlackStore(database, "workspace-a")
    claims = await asyncio.gather(first._claim("event"), second._claim("event"))
    assert sum(row is not None for row in claims) == 1
    claim = next(row for row in claims if row is not None)
    assert claim["data"]["notifications"]["result"]["sent"] is False
    await second._save(claim, release=True)
    assert await second._claim("event") is not None
    assert await _SlackStore(database, "workspace-b")._get("event") is None


def event(event_id="E1", user="U1", message="hello", channel="C1", thread="1.000"):
    return {
        "type": "event_callback",
        "team_id": "T1",
        "api_app_id": "A1",
        "event_id": event_id,
        "authorizations": [{"team_id": "T1", "user_id": "UBOT", "is_bot": True}],
        "event": {
            "type": "app_mention",
            "user": user,
            "channel": channel,
            "thread_ts": thread,
            "ts": "2.000",
            "text": message,
        },
    }


def signed(data, *, valid=True):
    body = json.dumps(data).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(SECRET.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": "v0=" + (digest if valid else "bad"),
    }


@pytest.fixture
def system(database, monkeypatch):
    from slack_sdk import WebClient

    posts = []
    outage = {"active": False}
    monkeypatch.setattr(
        WebClient, "auth_test", lambda self: {"ok": True, "team_id": "T1", "user_id": "UBOT", "bot_id": "B1"}
    )

    def post(self, **kwargs):
        if outage["active"]:
            raise RuntimeError("offline provider outage")
        posts.append(kwargs)
        return {"ok": True, "ts": str(len(posts))}

    monkeypatch.setattr(WebClient, "chat_postMessage", post)
    auth = Authorization(db=database, verification_keys=["offline-slack-jwt-key-at-least-32-bytes"], algorithm="HS256")
    auth.define_role(
        "member", ["teams:super-agent:run", "teams:super-agent:read", "sessions:read", "tasks:read", "company:read"]
    ).assign("alice", "member").assign("bob", "member")
    model = OfflineModel()
    delivery = SlackCompany("T1", "A1", "UBOT", {"U1": "alice", "U2": "bob"}, ("C1",), "https://os.example/company")
    interface = Slack(company=delivery, token="offline-token", signing_secret=SECRET, streaming=False)
    os = AgentOS(
        id="slack-test",
        db=database,
        manager=OSManager(model=model, access_docs=False),
        company=CompanyConfig(model=model),
        authorization=auth,
        user_isolation=True,
        queue=QueueConfig(durable=True, poll_interval=0.01),
        scheduler=True,
        scheduler_poll_interval=3600,
        interfaces=[interface],
        telemetry=False,
    )
    app = os.get_app()
    with TestClient(app) as client:
        yield client, os, delivery, posts, outage, auth, model


def force_delivery(client, delivery, receipt_id):
    # Simulate the existing scheduler's next tick without waiting for the cron.
    def reset(conn):
        conn.execute(
            delivery._store.table.update()
            .where(delivery._store.table.c.id == receipt_id)
            .values(next_at=0, lease_until=0)
        )

    client.portal.call(delivery._store._call, reset)
    client.portal.call(delivery._process, client.app, receipt_id)


def test_signed_identity_duplicate_intake_and_eventual_delivery(system):
    client, os, delivery, posts, outage, auth, model = system
    body, headers = signed(event())
    assert (
        client.post("/slack/events", content=body, headers={**headers, "X-Slack-Signature": "v0=bad"}).status_code
        == 403
    )
    wrong = event("wrong")
    wrong["team_id"] = "T2"
    content, signed_headers = signed(wrong)
    assert client.post("/slack/events", content=content, headers=signed_headers).status_code == 403
    for data in (event("unknown", user="U3"), event("channel", channel="C2")):
        content, signed_headers = signed(data)
        assert client.post("/slack/events", content=content, headers=signed_headers).status_code == 403
    outage["active"] = True
    assert client.post("/slack/events", content=body, headers=headers).status_code == 200
    assert client.post("/slack/events", content=body, headers={**headers, "X-Slack-Retry-Num": "1"}).status_code == 200
    receipt_id = _identity(delivery._scope, "E1")
    row = client.portal.call(delivery._store._get, receipt_id)
    assert row["data"]["state"] == "submitted", row
    for _ in range(200):
        run = os.manager.db.get_run(row["data"]["run_id"])
        if run is not None and str(getattr(run.status, "value", run.status)).upper() == "COMPLETED":
            break
        time.sleep(0.01)
    assert model.calls == 1
    # Reconstruct storage/service state as after a restart; posting failure
    # must neither lose the result nor re-execute the completed model run.
    delivery._store = _SlackStore(os._company_db, delivery._scope)
    outage["active"] = False
    force_delivery(client, delivery, receipt_id)
    assert any("Offline response" in post["text"] for post in posts)
    assert model.calls == 1
    force_delivery(client, delivery, receipt_id)
    assert len(posts) == 2
    assert model.calls == 1
    content, signed_headers = signed(event("E2", user="U2"))
    assert client.post("/slack/events", content=content, headers=signed_headers).status_code == 200
    second = client.portal.call(delivery._store._get, _identity(delivery._scope, "E2"))
    assert second["session_id"] != row["session_id"]


def test_revoked_access_and_bot_echo_do_not_deliver_private_results(system):
    client, os, delivery, posts, outage, auth, model = system
    bot = event("bot")
    bot["event"]["bot_id"] = "BOTHER"
    body, headers = signed(bot)
    assert client.post("/slack/events", content=body, headers=headers).status_code == 200
    assert model.calls == 0
    outage["active"] = True
    body, headers = signed(event("revoke"))
    assert client.post("/slack/events", content=body, headers=headers).status_code == 200
    receipt_id = _identity(delivery._scope, "revoke")
    auth.set_role_scopes("member", [])
    outage["active"] = False
    force_delivery(client, delivery, receipt_id)
    force_delivery(client, delivery, receipt_id)
    assert not any("Offline response" in post["text"] for post in posts)
    assert any("current platform access" in post["text"] for post in posts)


def test_receipt_dedup_survives_queue_retention(system):
    client, os, delivery, posts, outage, auth, model = system
    body, headers = signed(event("retention"))
    assert client.post("/slack/events", content=body, headers=headers).status_code == 200
    receipt_id = _identity(delivery._scope, "retention")
    row = client.portal.call(delivery._store._get, receipt_id)
    for _ in range(200):
        run = os.manager.db.get_run(row["data"]["run_id"])
        if run is not None and str(getattr(run.status, "value", run.status)).upper() == "COMPLETED":
            break
        time.sleep(0.01)
    assert model.calls == 1
    # Crash window: execution committed but the receipt did not advance. Its
    # stable run id must still fence a replay after the queue row is removed.
    row["data"]["state"] = "received"

    def rewind(conn):
        conn.execute(
            delivery._store.table.update()
            .where(delivery._store.table.c.id == receipt_id)
            .values(data=row["data"], next_at=0, lease_until=0)
        )

    client.portal.call(delivery._store._call, rewind)
    queue = client.app.state.queue_worker
    client.portal.call(queue.store.cleanup_jobs, -1)
    force_delivery(client, delivery, receipt_id)
    assert model.calls == 1


def test_streaming_delivery_uses_existing_slack_transport(system):
    client, os, delivery, posts, outage, auth, model = system
    streams = []

    class Stream:
        async def append(self, **kwargs):
            streams.append(kwargs["markdown_text"])

        async def stop(self):
            return {"ok": True, "ts": "stream"}

    class Client:
        async def chat_stream(self, **kwargs):
            assert kwargs["recipient_user_id"] == "U1" and kwargs["recipient_team_id"] == "T1"
            return Stream()

    delivery._stream_client = Client()
    body, headers = signed(event("stream"))
    assert client.post("/slack/events", content=body, headers=headers).status_code == 200
    receipt_id = _identity(delivery._scope, "stream")
    row = client.portal.call(delivery._store._get, receipt_id)
    for _ in range(200):
        run = os.manager.db.get_run(row["data"]["run_id"])
        if run is not None and str(getattr(run.status, "value", run.status)).upper() == "COMPLETED":
            break
        time.sleep(0.01)
    force_delivery(client, delivery, receipt_id)
    assert streams == ["Offline response"]


def test_tool_confirmation_is_bound_to_original_participant(system):
    from agno.tools import tool
    from urllib.parse import urlencode

    client, os, delivery, posts, outage, auth, model = system
    calls = []

    @tool(requires_confirmation=True)
    def approved_local_action() -> str:
        """Run the controlled fixture action after confirmation."""
        calls.append(True)
        return "verified local output"

    os.manager.tools.append(approved_local_action)
    model.next_tool = "approved_local_action"
    body, headers = signed(event("approval"))
    assert client.post("/slack/events", content=body, headers=headers).status_code == 200
    receipt_id = _identity(delivery._scope, "approval")
    row = client.portal.call(delivery._store._get, receipt_id)
    for _ in range(200):
        run = os.manager.db.get_run(row["data"]["run_id"])
        if run is not None and str(getattr(run.status, "value", run.status)).upper() == "PAUSED":
            break
        time.sleep(0.01)
    assert run.status.value == "PAUSED" and not calls
    force_delivery(client, delivery, receipt_id)
    assert any(post.get("blocks") for post in posts)
    req = run.requirements[0]
    payload = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "api_app_id": "A1",
        "user": {"id": "U2"},
        "channel": {"id": "C1"},
        "message": {"ts": "3.000", "thread_ts": "1.000"},
        "actions": [{"action_id": "row_approve", "value": req.id + "|" + run.run_id + "|", "action_ts": "4.000"}],
    }

    def click(data):
        encoded = urlencode({"payload": json.dumps(data)}).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(SECRET.encode(), b"v0:" + timestamp.encode() + b":" + encoded, hashlib.sha256).hexdigest()
        return client.post(
            "/slack/interactions",
            content=encoded,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": "v0=" + signature,
            },
        )

    assert click(payload).status_code == 403 and not calls
    payload["user"]["id"] = "U1"
    assert click(payload).status_code == 200
    for _ in range(200):
        if calls:
            break
        time.sleep(0.01)
    assert calls == [True]
    assert click(payload).status_code == 200
    assert calls == [True]


def test_disabled_user_cannot_receive_delayed_result(system):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    client, os, delivery, posts, outage, auth, model = system
    outage["active"] = True
    body, headers = signed(event("disabled"))
    assert client.post("/slack/events", content=body, headers=headers).status_code == 200
    client.app.state.user_store = SimpleNamespace(ais_disabled=AsyncMock(return_value=True))
    outage["active"] = False
    receipt_id = _identity(delivery._scope, "disabled")
    force_delivery(client, delivery, receipt_id)
    force_delivery(client, delivery, receipt_id)
    assert not any("Offline response" in post["text"] for post in posts)
    assert any("current platform access" in post["text"] for post in posts)


def test_same_second_task_transitions_have_distinct_delivery_intents(system, monkeypatch):
    from unittest.mock import AsyncMock

    client, os, delivery, posts, outage, auth, model = system
    body, headers = signed(event("transitions"))
    assert client.post("/slack/events", content=body, headers=headers).status_code == 200
    receipt_id = _identity(delivery._scope, "transitions")
    row = client.portal.call(delivery._store._get, receipt_id)
    task = {"task_id": "task-1", "title": "Verified artifact", "status": "in_review", "updated_at": 100, "run_id": "attempt-1", "result": "first output"}
    reader = AsyncMock(return_value=[task])
    monkeypatch.setattr("agno.company.conversation.aget_conversation_tasks", reader)
    client.portal.call(delivery._collect, client.app, row)
    task.update(status="backlog", reason="Needs revision")
    client.portal.call(delivery._collect, client.app, row)
    task.update(status="done", run_id="attempt-2", result="Verified revision", reason=None)
    client.portal.call(delivery._collect, client.app, row)
    intents = [value for key, value in row["data"]["notifications"].items() if key.startswith("task:")]
    assert len(intents) == 3
    assert any("Verified revision" in item["text"] for item in intents)
    assert any("assessing the evidence" in item["text"] for item in intents)
