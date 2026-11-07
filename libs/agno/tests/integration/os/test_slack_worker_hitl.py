"""Signed Slack worker tool approvals through PostgreSQL Task and queue state."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.job_queue import QueueConfig
from agno.os import AgentOS, Authorization, CompanyConfig, OSManager
from agno.os.interfaces.slack import Slack, SlackCompany
from agno.os.interfaces.slack.company import _identity
from agno.team import Team
from agno.tools import tool
from tests.integration.db.test_company_conversation import ConversationModel
from tests.integration.os import test_slack_company
from tests.integration.os.test_slack_company import SECRET, OfflineModel, event, force_delivery, signed

database = test_slack_company.database


@pytest.fixture
def worker_system(database, monkeypatch, request):
    mode = getattr(request, "param", "agent-confirm")
    kind = mode.split("-")[0]
    from slack_sdk import WebClient

    posts, calls = [], []
    monkeypatch.setattr(
        WebClient, "auth_test", lambda self: {"ok": True, "team_id": "T1", "user_id": "UBOT", "bot_id": "B1"}
    )

    def post(self, **kwargs):
        posts.append(kwargs)
        return {"ok": True, "ts": str(len(posts))}

    monkeypatch.setattr(WebClient, "chat_postMessage", post)
    auth = Authorization(db=database, verification_keys=["offline-slack-jwt-key-at-least-32-bytes"], algorithm="HS256")
    auth.define_role("owner", ["agent_os:admin"]).assign("platform-owner", "owner")
    auth.define_role(
        "member",
        [
            "teams:super-agent:run",
            "teams:super-agent:read",
            "sessions:read",
            "tasks:read",
            "tasks:write",
            "wiki:read",
            "company:read",
            "products:write",
            "projects:write",
            "agents:writer:read",
            "agents:writer:run",
            "teams:writer:read",
            "teams:writer:run",
        ],
    ).assign("alice", "member").assign("bob", "member")

    @tool(requires_confirmation=True)
    def approved_worker_action() -> str:
        """Run the controlled worker action after confirmation."""
        calls.append(True)
        return "Verified worker output"

    @tool(requires_user_input=True, user_input_fields=["answer"])
    def input_worker_action(answer: str) -> str:
        """Use an input provided by the originating participant."""
        calls.append(answer)
        return "Verified input " + answer

    worker_model = OfflineModel()
    selected = input_worker_action if mode.endswith("input") else approved_worker_action
    worker_model.next_tool = selected.name
    writer = (
        Agent(id="writer", model=worker_model, tools=[selected], db=database, telemetry=False)
        if kind == "agent"
        else Team(id="writer", model=worker_model, tools=[selected], members=[], db=database, telemetry=False)
    )
    model = ConversationModel()
    delivery = SlackCompany("T1", "A1", "UBOT", {"U1": "alice", "U2": "bob"}, ("C1",), "https://os.example/company")
    interface = Slack(company=delivery, token="offline-token", signing_secret=SECRET, streaming=False)
    os = AgentOS(
        id="slack-worker-test",
        db=database,
        agents=[writer] if kind == "agent" else [],
        teams=[writer] if kind == "team" else [],
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
        token = jwt.encode(
            {"sub": "alice", "exp": time.time() + 600}, "offline-slack-jwt-key-at-least-32-bytes", algorithm="HS256"
        )
        headers = {"Authorization": "Bearer " + token}
        product = client.post("/company/products", json={"name": "Product"}, headers=headers).json()
        project = client.post(
            "/company/projects", json={"product_id": product["id"], "name": "Project"}, headers=headers
        ).json()
        assert (
            client.post(
                "/company/projects/" + project["id"] + "/transitions",
                json={"target": "active", "reason": "Test outcome"},
                headers=headers,
            ).status_code
            == 200
        )
        task = client.post(
            "/company/tasks",
            json={
                "product_id": product["id"],
                "project_id": project["id"],
                "title": "Confirm worker",
                "brief": "Run the confirmed action",
            },
            headers=headers,
        ).json()
        accepted = client.post(
            "/company/tasks/" + task["id"] + "/transitions",
            json={"target": "ready", "reason": "Test accepted task", "executor_type": kind, "executor_id": "writer"},
            headers=headers,
        )
        assert accepted.status_code == 200, accepted.text
        body, signed_headers = signed(event("worker-approval", message="submit:" + task["id"]))
        assert client.post("/slack/events", content=body, headers=signed_headers).status_code == 200
        receipt_id = _identity(delivery._scope, "worker-approval")
        run = None
        for _ in range(300):
            task = database.get_task(task["id"])
            run = database.get_run(task["job_id"]) if task.get("job_id") else None
            if run is not None and run.status.value == "PAUSED":
                break
            time.sleep(0.01)
        assert run is not None and run.status.value == "PAUSED", task
        force_delivery(client, delivery, receipt_id)
        yield client, os, delivery, posts, calls, auth, task, run, receipt_id


def click(client, run, *, user="U1", thread="1.000", req_id=None, stamp="4.000", input_value=None):
    payload = {
        "type": "block_actions",
        "team": {"id": "T1"},
        "api_app_id": "A1",
        "user": {"id": user},
        "channel": {"id": "C1"},
        "message": {"ts": "3.000", "thread_ts": thread},
        "actions": [
            {
                "action_id": "row_approve",
                "value": (req_id or run.requirements[0].id) + "|" + run.run_id + "|",
                "action_ts": stamp,
            }
        ],
    }
    if input_value is not None:
        from agno.os.interfaces.slack.ids import user_input_action_id, user_input_block_id

        requirement = run.requirements[0]
        payload["actions"] = [
            {
                "action_id": "submit_pause",
                "block_id": "pause:" + run.run_id,
                "value": run.run_id + "|",
                "action_ts": stamp,
            }
        ]
        payload["state"] = {
            "values": {
                user_input_block_id(requirement.id, "answer"): {
                    user_input_action_id("answer"): {"type": "plain_text_input", "value": input_value}
                }
            }
        }
    body = urlencode({"payload": json.dumps(payload)}).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(SECRET.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    return client.post(
        "/slack/interactions",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": "v0=" + signature,
        },
    )


def test_worker_confirmation_is_durable_and_bound_to_origin(worker_system):
    client, os, delivery, posts, calls, auth, task, run, receipt_id = worker_system
    row = client.portal.call(delivery._store._get, receipt_id)
    assert "worker_runs" in row["data"], row
    assert row["data"]["worker_runs"][run.run_id]["task_id"] == task["id"]
    assert any(post.get("blocks") and "worker" in post["text"] for post in posts)
    assert not calls
    assert click(client, run, user="U2").status_code == 403
    assert click(client, run, thread="wrong").status_code == 403
    assert click(client, run, req_id="wrong").status_code == 400
    # Reconstruct durable receipt access as after restart; the mapping does not rely on RAM.
    from agno.os.interfaces.slack.store import _SlackStore

    delivery._store = _SlackStore(os._company_db, delivery._scope)
    assert click(client, run).status_code == 200
    for _ in range(300):
        if calls:
            break
        time.sleep(0.01)
    assert calls == [True]
    assert click(client, run).status_code == 200
    assert calls == [True]
    for _ in range(300):
        if os._company_db.get_task(task["id"])["status"] == "in_review":
            break
        time.sleep(0.01)
    assert os._company_db.get_task(task["id"])["status"] == "in_review"


def test_worker_confirmation_rechecks_revoked_authority(worker_system):
    client, os, delivery, posts, calls, auth, task, run, receipt_id = worker_system
    auth.unassign("alice", "member")
    assert click(client, run).status_code == 403
    assert calls == []


def test_worker_confirmation_rejects_changed_task_attempt(worker_system):
    client, os, delivery, posts, calls, auth, task, run, receipt_id = worker_system
    table = os._company_db._get_table(table_type="tasks")
    with os._company_db.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.id == task["id"]).values(job_id="new-attempt"))
    assert click(client, run).status_code == 403
    assert calls == []


@pytest.mark.parametrize("worker_system", ["team-confirm", "agent-input", "team-input"], indirect=True)
def test_team_and_user_input_continue_same_worker(worker_system, request):
    client, os, delivery, posts, calls, auth, task, run, receipt_id = worker_system
    needs_input = bool(run.requirements[0].user_input_schema)
    response = click(client, run, input_value="Required context" if needs_input else None)
    assert response.status_code == 200, response.text
    for _ in range(300):
        if calls:
            break
        time.sleep(0.01)
    assert calls == (["Required context"] if needs_input else [True])
    assert os._company_db.get_task(task["id"])["job_id"] == run.run_id


def test_delayed_pause_arguments_recheck_executor_read(worker_system):
    client, os, delivery, posts, calls, auth, task, run, receipt_id = worker_system
    row = client.portal.call(delivery._store._get, receipt_id)
    pause = next(value for value in row["data"]["notifications"].values() if value.get("worker"))
    pause["sent"] = False
    auth.set_role_scopes(
        "member", ["teams:super-agent:run", "teams:super-agent:read", "sessions:read", "tasks:read", "company:read"]
    )
    before = len(posts)
    client.portal.call(delivery._deliver, client.app, row)
    assert len(posts) == before
    assert pause["suppressed"] is True
    assert click(client, run).status_code == 403
    assert not calls


def test_slack_company_requires_participant_session_isolation():
    from types import SimpleNamespace

    delivery = SlackCompany("T1", "A1", "UBOT", {"U1": "alice"}, ("C1",), "https://os.example/company")
    with pytest.raises(ValueError, match="user_isolation=True"):
        delivery._bind(SimpleNamespace(user_isolation=False), "/slack")


@pytest.mark.parametrize("worker_system", ["agent-confirm", "team-confirm"], indirect=True)
def test_settling_worker_approval_retries_durably(worker_system):
    from sqlalchemy import select

    client, os, delivery, posts, calls, auth, task, run, receipt_id = worker_system
    table = os._company_db._get_table(table_type="jobs")
    # Reproduce the real boundary: the paused run committed before its ticket parked.
    with os._company_db.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.id == run.run_id).values(status="running"))
    assert click(client, run).status_code == 200

    def continuation(conn):
        row = conn.execute(
            select(delivery._store.table).where(
                delivery._store.table.c.scope == delivery._scope,
                delivery._store.table.c.data["kind"].as_string() == "continue",
                delivery._store.table.c.data["run_id"].as_string() == run.run_id,
            )
        ).one()
        return dict(row._mapping)

    receipt = client.portal.call(delivery._store._call, continuation)
    assert receipt["data"]["state"] == "received", receipt
    assert receipt["data"]["attempts"] == 1
    assert not calls
    with os._company_db.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.id == run.run_id).values(status="paused"))
    force_delivery(client, delivery, receipt["id"])
    for _ in range(300):
        if calls:
            break
        time.sleep(0.01)
    assert calls == [True]
