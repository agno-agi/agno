"""The GitHub interface accepts only signed deliveries for watched repositories and hands each event to its handler."""

import asyncio
import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.interfaces.github import GitHub, GitHubEvent

SECRET = "github-webhook-secret"


def issue_opened(**overrides):
    payload = {
        "action": "opened",
        "repository": {"full_name": "agno-agi/agno"},
        "sender": {"login": "alice", "type": "User"},
        "issue": {
            "number": 7,
            "title": "Export fails",
            "body": "Steps to reproduce...",
            "html_url": "https://github.com/agno-agi/agno/issues/7",
            "state": "open",
            "user": {"login": "alice"},
        },
    }
    payload.update(overrides)
    return payload


def deliver(client, payload, event="issues", secret=SECRET, delivery="d-1", signature=None):
    body = json.dumps(payload).encode()
    if signature is None:
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": delivery, "Content-Type": "application/json"}
    if signature:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/github/events", content=body, headers=headers)


@pytest.fixture
def received():
    return []


@pytest.fixture
def client(received):
    async def handler(event: GitHubEvent):
        received.append(event)
        return {"task_id": "t-1"}

    interface = GitHub(handler, repositories=["Agno-AGI/agno"], webhook_secret=SECRET)
    app = FastAPI()
    app.include_router(interface.get_router())
    return TestClient(app)


def test_a_signed_new_issue_reaches_the_handler(client, received):
    response = deliver(client, issue_opened())
    assert response.status_code == 202
    assert response.json() == {"status": "recorded", "delivery_id": "d-1", "result": {"task_id": "t-1"}}

    event = received[0]
    assert (event.delivery_id, event.kind, event.repository, event.sender) == (
        "d-1",
        "issues.opened",
        "agno-agi/agno",
        "alice",
    )
    assert event.issue == {
        "number": 7,
        "title": "Export fails",
        "body": "Steps to reproduce...",
        "url": "https://github.com/agno-agi/agno/issues/7",
        "state": "open",
        "author": "alice",
        "pull_request": False,
    }
    assert event.comment is None and event.payload["action"] == "opened"
    # A repository webhook names no installation; a GitHub App's delivery does.
    assert event.installation_id is None
    assert deliver(client, issue_opened(installation={"id": 42}), delivery="d-app").status_code == 202
    assert received[1].installation_id == 42


def test_a_github_apps_own_comments_are_ignored(client, received):
    own = issue_opened(sender={"login": "agno-super-agent[bot]", "type": "Bot"}, installation={"id": 42})
    assert deliver(client, own).json() == {"status": "ignored", "reason": "sent by agno-super-agent[bot]"}
    assert received == []


@pytest.mark.parametrize(
    "signature, status",
    [("", 400), ("sha256=" + "0" * 64, 403), ("sha1=abc", 403)],
    ids=["missing", "wrong", "not-sha256"],
)
def test_unsigned_or_wrongly_signed_deliveries_are_refused(client, received, signature, status):
    assert deliver(client, issue_opened(), signature=signature).status_code == status
    assert deliver(client, issue_opened(), secret="another-secret").status_code == 403
    assert received == []


def test_ping_and_malformed_deliveries(client, received):
    assert deliver(client, {"zen": "Keep it simple."}, event="ping").json() == {"status": "pong"}
    body = b"not json"
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = client.post(
        "/github/events",
        content=body,
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "d-2", "X-Hub-Signature-256": signature},
    )
    assert response.status_code == 400
    missing_event = client.post("/github/events", content=b"{}", headers={"X-Hub-Signature-256": "sha256=x"})
    assert missing_event.status_code == 403
    assert received == []


@pytest.mark.parametrize(
    "payload, event, reason",
    [
        (issue_opened(repository={"full_name": "someone/else"}), "issues", "repository someone/else is not watched"),
        (issue_opened(action="edited"), "issues", "issues.edited is not handled"),
        (issue_opened(sender={"login": "dependabot[bot]", "type": "Bot"}), "issues", "sent by dependabot[bot]"),
        ({"action": "opened", "sender": {"login": "alice"}}, "issues", "the delivery names no repository"),
    ],
    ids=["other-repository", "other-action", "bot", "no-repository"],
)
def test_events_outside_the_watch_are_acknowledged_and_ignored(client, received, payload, event, reason):
    response = deliver(client, payload, event=event)
    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "reason": reason}
    assert received == []


def test_comments_are_handled(client, received):
    comment = {
        "action": "created",
        "repository": {"full_name": "agno-agi/agno"},
        "sender": {"login": "alice", "type": "User"},
        "issue": {"number": 9, "title": "Add retries", "pull_request": {"url": "..."}, "user": {"login": "bob"}},
        "comment": {
            "id": 11,
            "body": "@agno investigate",
            "html_url": "https://github.com/c/11",
            "user": {"login": "alice"},
        },
    }
    assert deliver(client, comment, event="issue_comment").status_code == 202
    assert received[0].issue["pull_request"] is True
    assert received[0].comment == {
        "id": 11,
        "body": "@agno investigate",
        "url": "https://github.com/c/11",
        "author": "alice",
    }

    # Text a person writes is handled whatever it contains, hidden HTML comments included.
    hidden = {**comment, "comment": {**comment["comment"], "body": "Same here <!-- agno:task=t-1 -->"}}
    assert deliver(client, hidden, event="issue_comment", delivery="d-2").status_code == 202
    assert len(received) == 2


def test_a_handler_failure_asks_for_a_redelivery():
    def failing(event):
        raise RuntimeError("database unavailable")

    app = FastAPI()
    app.include_router(GitHub(failing, repositories=["agno-agi/agno"], webhook_secret=SECRET).get_router())
    response = deliver(TestClient(app), issue_opened())
    assert response.status_code == 500
    assert "redeliver" in response.json()["detail"]


def test_configuration_is_checked(monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    with pytest.raises(ValueError, match="webhook secret"):
        GitHub(lambda event: None, repositories=["agno-agi/agno"])
    for repositories in ([], ["agno"], ["a/b/c"], ["/agno"]):
        with pytest.raises(ValueError, match="owner/name"):
            GitHub(lambda event: None, repositories=repositories, webhook_secret=SECRET)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    assert GitHub(lambda event: None, repositories=["agno-agi/agno"]).webhook_secret == SECRET
    # A single string is one repository or event, not a sequence of characters.
    single = GitHub(lambda event: None, repositories="Agno-AGI/agno", events="issues.opened")
    assert single.repositories == {"agno-agi/agno"} and single.events == {"issues.opened"}


def test_agentos_serves_deliveries_without_its_own_bearer_token(received):
    # The signature is the authentication: GitHub cannot send an AgentOS token.
    interface = GitHub(lambda event: received.append(event), repositories=["agno-agi/agno"], webhook_secret=SECRET)
    agent_os = AgentOS(
        id="github-interface",
        agents=[Agent(id="reader")],
        interfaces=[interface],
        telemetry=False,
        authorization=Authorization(verification_keys=["a-verification-key-of-at-least-32-bytes"], algorithm="HS256"),
    )
    client = TestClient(agent_os.get_app())
    assert deliver(client, issue_opened()).status_code == 202
    assert deliver(client, issue_opened(), signature="sha256=" + "0" * 64).status_code == 403
    assert len(received) == 1


def app_for(handler, **options):
    app = FastAPI()
    app.include_router(GitHub(handler, repositories=["agno-agi/agno"], webhook_secret=SECRET, **options).get_router())
    return app


def test_a_redelivery_runs_the_handler_once_unless_the_first_attempt_failed():
    calls = []

    def handler(event):
        calls.append(event.delivery_id)
        if len(calls) == 2:
            raise RuntimeError("database unavailable")
        return {"task_id": f"t-{len(calls)}"}

    client = TestClient(app_for(handler))
    first = deliver(client, issue_opened(), delivery="d-1").json()
    again = deliver(client, issue_opened(), delivery="d-1").json()
    assert again == {**first, "duplicate": True} and calls == ["d-1"]

    # A failed delivery is forgotten, so GitHub's redelivery retries it.
    assert deliver(client, issue_opened(), delivery="d-2").status_code == 500
    retried = deliver(client, issue_opened(), delivery="d-2")
    assert retried.status_code == 202 and "duplicate" not in retried.json()
    assert calls == ["d-1", "d-2", "d-2"]


def test_a_redelivery_during_a_slow_first_attempt_waits_for_it():
    started, release, calls = asyncio.Event(), asyncio.Event(), []

    async def handler(event):
        calls.append(event.delivery_id)
        started.set()
        await release.wait()
        return {"task_id": "t-1"}

    async def scenario():
        transport = httpx.ASGITransport(app=app_for(handler))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            body = json.dumps(issue_opened()).encode()
            signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
            headers = {"X-GitHub-Event": "issues", "X-GitHub-Delivery": "d-1", "X-Hub-Signature-256": signature}
            first = asyncio.create_task(client.post("/github/events", content=body, headers=headers))
            await started.wait()
            second = asyncio.create_task(client.post("/github/events", content=body, headers=headers))
            await asyncio.sleep(0.05)
            assert not second.done()
            release.set()
            return (await first).json(), (await second).json()

    first, second = asyncio.run(scenario())
    assert second == {**first, "duplicate": True} and calls == ["d-1"]


def test_sync_handlers_run_in_the_threadpool():
    threads = set()

    def slow(event):
        threads.add(threading.get_ident())
        time.sleep(0.5)

    async def scenario():
        transport = httpx.ASGITransport(app=app_for(slow))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            requests = []
            for index in range(3):
                body = json.dumps(issue_opened()).encode()
                signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
                headers = {
                    "X-GitHub-Event": "issues",
                    "X-GitHub-Delivery": f"d-{index}",
                    "X-Hub-Signature-256": signature,
                }
                requests.append(client.post("/github/events", content=body, headers=headers))
            started = time.monotonic()
            responses = await asyncio.gather(*requests)
            return time.monotonic() - started, [response.status_code for response in responses]

    elapsed, statuses = asyncio.run(scenario())
    # One after another would take 1.5s; on the event loop thread they would block every other request.
    assert statuses == [202, 202, 202] and elapsed < 1.2
    assert threading.get_ident() not in threads


@dataclass
class Receipt:
    task_id: str
    at: datetime


def test_a_recorded_event_is_never_reported_as_failed():
    # Results the encoder handles are sent back under "result", which can't replace the status.
    at = datetime(2026, 11, 11, tzinfo=timezone.utc)
    client = TestClient(app_for(lambda event: Receipt("t-1", at)))
    assert deliver(client, issue_opened()).json()["result"] == {"task_id": "t-1", "at": "2026-11-11T00:00:00+00:00"}
    client = TestClient(app_for(lambda event: {"status": "overwritten"}))
    assert deliver(client, issue_opened()).json() == {
        "status": "recorded",
        "delivery_id": "d-1",
        "result": {"status": "overwritten"},
    }
    # A result that can't be sent back is left out; the event is still recorded, not a 500.
    client = TestClient(app_for(lambda event: {"lock": threading.Lock()}))
    response = deliver(client, issue_opened())
    assert response.status_code == 202 and response.json() == {"status": "recorded", "delivery_id": "d-1"}


def test_bot_events_can_be_handled_when_asked():
    received = []
    bot = issue_opened(sender={"login": "dependabot[bot]", "type": "Bot"})
    assert deliver(TestClient(app_for(received.append)), bot).json()["status"] == "ignored"
    assert deliver(TestClient(app_for(received.append, handle_bot_events=True)), bot).status_code == 202
    assert [event.sender for event in received] == ["dependabot[bot]"]


def test_form_encoded_deliveries_are_read_like_json(received):
    # The REST API creates repository webhooks with the form content type unless told otherwise.
    client = TestClient(app_for(received.append))
    body = urlencode({"payload": json.dumps(issue_opened())}).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "d-form",
        "X-Hub-Signature-256": signature,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    response = client.post("/github/events", content=body, headers=headers)
    assert response.status_code == 202 and received[0].issue["number"] == 7
    empty = b"other=1"
    signature = "sha256=" + hmac.new(SECRET.encode(), empty, hashlib.sha256).hexdigest()
    headers.update({"X-GitHub-Delivery": "d-empty", "X-Hub-Signature-256": signature})
    assert client.post("/github/events", content=empty, headers=headers).status_code == 400


def test_two_interfaces_share_an_app_with_their_own_routes(recwarn):
    interfaces = [
        GitHub(lambda event: None, repositories=["agno-agi/agno"], webhook_secret=SECRET),
        GitHub(lambda event: None, repositories=["agno-agi/docs"], webhook_secret=SECRET, prefix="/github/docs"),
    ]
    app = FastAPI()
    for interface in interfaces:
        router = interface.get_router()
        assert interface.router is router
        app.include_router(router)
    operation_ids = [
        operation["operationId"] for path in app.openapi()["paths"].values() for operation in path.values()
    ]
    assert sorted(operation_ids) == [
        "github_events_github",
        "github_events_github_docs",
        "github_status_github",
        "github_status_github_docs",
    ]
    assert not [warning for warning in recwarn if "Duplicate Operation ID" in str(warning.message)]
    client = TestClient(app)
    assert client.get("/github/status").json() == {"status": "available"}
    assert client.get("/github/docs/status").json() == {"status": "available"}
