"""The GitHub interface accepts only signed deliveries for watched repositories and hands each event to its handler."""

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.interfaces.github import GitHub, GitHubEvent
from agno.os.interfaces.github.events import MARKER

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

    interface = GitHub(handler, repositories=["Agno-AGI/agno"], webhook_secret=SECRET, ignore_logins=["agno-bot"])
    app = FastAPI()
    app.include_router(interface.get_router())
    return TestClient(app)


def test_a_signed_new_issue_reaches_the_handler(client, received):
    response = deliver(client, issue_opened())
    assert response.status_code == 202
    assert response.json() == {"status": "recorded", "task_id": "t-1"}

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
        (issue_opened(sender={"login": "Agno-Bot", "type": "User"}), "issues", "sent by Agno-Bot"),
        ({"action": "opened", "sender": {"login": "alice"}}, "issues", "the delivery names no repository"),
    ],
    ids=["other-repository", "other-action", "bot", "own-login", "no-repository"],
)
def test_events_outside_the_watch_are_acknowledged_and_ignored(client, received, payload, event, reason):
    response = deliver(client, payload, event=event)
    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "reason": reason}
    assert received == []


def test_comments_are_handled_and_agnos_own_are_not(client, received):
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

    own = {**comment, "comment": {**comment["comment"], "body": f"Findings\n{MARKER}task=t-1 attempt=1 -->"}}
    assert deliver(client, own, event="issue_comment").json() == {"status": "ignored", "reason": "written by Agno"}
    assert len(received) == 1


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
