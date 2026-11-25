"""
Triggers Created Over The API And By An Agent
=============================================

Sources are code and triggers are data. The GitHub source is declared here, in
code. The triggers on it are created while the app runs: one over REST, and one
by an agent that holds TriggerTools.

    GET  /triggers/sources                        the sources and the event kinds each sends
    POST /triggers                                create a trigger on one of them
    GET  /triggers/events                         stored events, with status and reason
    POST /triggers/{id}/events/{event_id}/replay  run a finished event again

Check locally, without GitHub (serves in this process and sends it signed deliveries):
    .venvs/demo/bin/python cookbook/05_agent_os/33_triggers/stored_triggers.py --check

Serve for a repository webhook or a GitHub App (see README.md):
    export GITHUB_WEBHOOK_SECRET=<the webhook's secret>
    export GITHUB_REPOSITORY=owner/name
    .venvs/demo/bin/python cookbook/05_agent_os/33_triggers/stored_triggers.py
"""

import hashlib
import hmac
import json
import sys
import threading
import time
from os import getenv
from pathlib import Path
from typing import Any, Dict, List

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.github import GitHub
from agno.tools.triggers import TriggerTools

check = "--check" in sys.argv
CHECK_PORT = 7792
OS_ID = "stored-triggers"
secret = "local-check-secret" if check else getenv("GITHUB_WEBHOOK_SECRET")
repository = "agno-agi/agno" if check else getenv("GITHUB_REPOSITORY", "")

# ---------------------------------------------------------------------------
# Create the database
# ---------------------------------------------------------------------------
db_file = Path("tmp/stored_triggers_check.db" if check else "tmp/stored_triggers.db")
if check:
    # Each check starts from an empty database, so its deliveries are new.
    db_file.unlink(missing_ok=True)
db = SqliteDb(db_file=str(db_file))

# ---------------------------------------------------------------------------
# Declare the source
# ---------------------------------------------------------------------------
# No handler and no trigger in code: every verified delivery goes to the stored triggers.
github = GitHub(repositories=repository, webhook_secret=secret)

# ---------------------------------------------------------------------------
# Create the agents
# ---------------------------------------------------------------------------
triage_agent = Agent(
    id="issue-triage",
    name="Issue Triage",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions=[
        "You triage GitHub issues and pull requests. Choose one label from: bug, feature, question.",
        "Reply with the label and one short comment for the author.",
    ],
    add_history_to_context=True,
)

# This agent manages triggers for the people it talks to. It can create a trigger on a
# declared source; it cannot add a source.
operations_agent = Agent(
    id="operations",
    name="Operations",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[TriggerTools(db=db, sources=[github], os_id=OS_ID, add_instructions=True)],
    instructions=[
        "You set up automation for the team. Use your tools; do not ask follow-up questions."
    ],
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id=OS_ID,
    description="Triggers created over the API and by an agent",
    agents=[triage_agent, operations_agent],
    db=db,
    interfaces=[github],
    # A trigger starts its run on this server's own run endpoint.
    scheduler_base_url=f"http://127.0.0.1:{CHECK_PORT}" if check else None,
    telemetry=False,
)
app = agent_os.get_app()


def run_check() -> None:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=CHECK_PORT, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.1)
    api = httpx.Client(base_url=f"http://127.0.0.1:{CHECK_PORT}", timeout=60)

    def deliver(event: str, payload: Dict[str, Any], delivery: str) -> str:
        body = json.dumps(payload).encode()
        signature = (
            "sha256="
            + hmac.new(b"local-check-secret", body, hashlib.sha256).hexdigest()
        )
        headers = {
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": signature,
        }
        return api.post("/github/events", content=body, headers=headers).json()[
            "status"
        ]

    def finished_events() -> List[Dict[str, Any]]:
        deadline = time.time() + 180
        while True:
            events = api.get("/triggers/events", params={"limit": 50}).json()["data"]
            if not [e for e in events if e["status"] in ("pending", "running")]:
                return sorted(events, key=lambda stored: stored["id"])
            assert time.time() < deadline, "the runs did not finish in 3 minutes"
            time.sleep(1)

    opened = {
        "action": "opened",
        "repository": {"full_name": "agno-agi/agno"},
        "sender": {"login": "alice", "type": "User"},
        "issue": {
            "number": 1,
            "title": "Export to CSV drops the header row",
            "body": "Exporting a table with 3 columns writes no header row.",
            "html_url": "https://github.com/agno-agi/agno/issues/1",
            "user": {"login": "alice"},
            "author_association": "MEMBER",
        },
    }
    try:
        sources = api.get("/triggers/sources").json()
        print(
            "sources:",
            [(source["id"], len(source["event_kinds"])) for source in sources],
        )

        # Nothing listens yet: the delivery is stored as ignored, with the reason.
        print("issue with no trigger stored:", deliver("issues", opened, "d-1"))

        created = api.post(
            "/triggers",
            json={
                "name": "triage-issues",
                "source_id": "github",
                "events": ["issues.opened"],
                "continue_on": ["issue_comment.created"],
                "target_type": "agent",
                "target_id": "issue-triage",
                "input": "Triage this issue: choose a label and write a comment for its author.",
            },
        )
        assert created.status_code == 201, created.text
        trigger = created.json()
        print("trigger created over REST:", trigger["name"], trigger["filters"])

        refused = api.post(
            "/triggers",
            json={
                "name": "handle-posthog",
                "source_id": "posthog",
                "events": ["event"],
                "target_type": "agent",
                "target_id": "issue-triage",
                "input": "Handle it.",
            },
        )
        print("trigger on a source that is not declared:", refused.status_code)
        assert refused.status_code == 422

        print("the same issue, delivered again:", deliver("issues", opened, "d-2"))
        events = finished_events()
        ran = [event for event in events if event["trigger_id"] == trigger["id"]]
        assert [event["status"] for event in ran] == ["success"], ran

        replayed = api.post(f"/triggers/{trigger['id']}/events/{ran[0]['id']}/replay")
        assert replayed.status_code == 202, replayed.text
        print("replay accepted:", replayed.json()["status"])
        events = finished_events()
        ran = [event for event in events if event["trigger_id"] == trigger["id"]]
        assert [event["status"] for event in ran] == ["success", "success"], ran
        # A second run of its own, in the same conversation.
        assert ran[0]["run_id"] != ran[1]["run_id"]
        assert ran[0]["session_id"] == ran[1]["session_id"]

        # The agent creates a second trigger with its tools.
        answer = operations_agent.run(
            "Whenever a pull request is opened in our GitHub repository, have the issue-triage agent "
            "review it. Name the trigger review-pull-requests."
        )
        print("operations agent:", str(answer.content)[:200])
        stored = api.get("/triggers").json()["data"]
        by_name = {item["name"]: item for item in stored}
        assert "review-pull-requests" in by_name, sorted(by_name)
        review = by_name["review-pull-requests"]
        assert (
            review["events"] == ["pull_request.opened"]
            and review["target_id"] == "issue-triage"
        )

        print()
        for item in sorted(stored, key=lambda item: item["name"]):
            print(
                f"{item['name']}: {item['events']} -> {item['target_type']} {item['target_id']}"
            )
        for event in events:
            reason = f" ({event['reason']})" if event["reason"] else ""
            print(
                f"{event['delivery_id'][:24]} {event['kind']}: {event['status']}{reason}"
            )

        off = api.post(f"/triggers/{review['id']}/disable").json()
        assert off["enabled"] is False
        assert api.delete(f"/triggers/{review['id']}").status_code == 204
        assert len(api.get("/triggers").json()["data"]) == 1
        print()
        print(
            "A trigger created over REST ran for a delivery and was replayed as a second run in the same "
            "session. A source that is not declared was refused. The agent created a second trigger with "
            "its tools, and it was disabled and deleted over REST."
        )
    finally:
        api.close()
        server.should_exit = True
        thread.join(timeout=30)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if check:
        run_check()
    else:
        if not secret or not repository:
            raise SystemExit(
                "Set GITHUB_WEBHOOK_SECRET and GITHUB_REPOSITORY, or run with --check"
            )
        agent_os.serve(app="stored_triggers:app", port=7777, reload=False)
