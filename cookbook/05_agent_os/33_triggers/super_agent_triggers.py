"""
Super Agent Manages Triggers
============================

Super Agent holds TriggerTools when the AgentOS declares a source. Asked in
words, it creates a trigger on that source, lists it, turns it off and deletes
it. Deleting asks for confirmation first, as deleting a schedule does. It
cannot aim a trigger at one of its own internal members.

Check locally, without GitHub (runs the conversation in this process on a real model):
    .venvs/demo/bin/python cookbook/05_agent_os/33_triggers/super_agent_triggers.py --check

Serve for the AgentOS UI, then select Super Agent:
    export GITHUB_WEBHOOK_SECRET=<the webhook's secret>
    export GITHUB_REPOSITORY=owner/name
    .venvs/demo/bin/python cookbook/05_agent_os/33_triggers/super_agent_triggers.py
"""

import json
import sys
import time
from os import getenv
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager
from agno.os.interfaces.github import GitHub

check = "--check" in sys.argv
secret = "local-check-secret" if check else getenv("GITHUB_WEBHOOK_SECRET")
repository = "agno-agi/agno" if check else getenv("GITHUB_REPOSITORY", "")

# ---------------------------------------------------------------------------
# Create the database
# ---------------------------------------------------------------------------
db_file = Path(
    "tmp/super_agent_triggers_check.db" if check else "tmp/super_agent_triggers.db"
)
if check:
    db_file.unlink(missing_ok=True)
db = SqliteDb(db_file=str(db_file))

# ---------------------------------------------------------------------------
# Declare the source and the agent triggers can run
# ---------------------------------------------------------------------------
github = GitHub(repositories=repository, webhook_secret=secret)

triage_agent = Agent(
    id="issue-triage",
    name="Issue Triage",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions=[
        "You triage GitHub issues. Choose one label from: bug, feature, question.",
        "Reply with the label and one short comment for the author.",
    ],
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="super-agent-triggers",
    description="Super Agent manages triggers",
    agents=[triage_agent],
    db=db,
    interfaces=[github],
    # Super Agent gets TriggerTools because a source is declared.
    manager=OSManager(model=OpenAIResponses(id="gpt-5.6-luna"), access_docs=False),
    telemetry=False,
)
app = agent_os.get_app()


def run_check() -> None:
    from fastapi.testclient import TestClient

    session_id = "triggers-" + uuid4().hex[:8]

    def ask(client: TestClient, message: str) -> Dict[str, Any]:
        """Send one message to Super Agent, confirming a tool call if it asks to."""
        started = time.monotonic()
        response = client.post(
            "/teams/superagent/runs",
            data={"message": message, "session_id": session_id, "stream": "false"},
        )
        response.raise_for_status()
        run = response.json()
        confirmed: List[str] = []
        while run["status"] == "PAUSED":
            requirements = run.get("requirements") or []
            for requirement in requirements:
                tool = requirement.get("tool_execution") or {}
                if tool.get("requires_confirmation"):
                    requirement["confirmation"] = True
                    tool["confirmed"] = True
                    confirmed.append(tool.get("tool_name"))
            response = client.post(
                f"/teams/superagent/runs/{run['run_id']}/continue",
                data={
                    "requirements": json.dumps(requirements),
                    "session_id": session_id,
                    "stream": "false",
                },
            )
            response.raise_for_status()
            run = response.json()
        print(f"\n> {message}")
        if confirmed:
            print(f"[confirmed: {', '.join(confirmed)}]")
        print(f"({time.monotonic() - started:.0f}s) {str(run.get('content'))[:400]}")
        return {"content": str(run.get("content") or ""), "confirmed": confirmed}

    def triggers(client: TestClient) -> List[Dict[str, Any]]:
        return client.get("/triggers").json()["data"]

    with TestClient(app) as client:
        ask(
            client,
            "Whenever a new issue is opened in our GitHub repository, have the issue-triage agent triage it: "
            "choose a label and write a comment for the author. Name the trigger triage-new-issues.",
        )
        (created,) = triggers(client)
        assert created["name"] == "triage-new-issues", created
        assert (
            created["events"] == ["issues.opened"]
            and created["target_id"] == "issue-triage"
        )
        assert created["enabled"] is True and created["source_id"] == "github"

        listed = ask(client, "Which triggers do we have? Give their names.")
        assert "triage-new-issues" in listed["content"]

        ask(client, "Turn the triage-new-issues trigger off.")
        (stored,) = triggers(client)
        assert stored["enabled"] is False, stored

        deleted = ask(client, "Delete the triage-new-issues trigger.")
        assert "delete_trigger" in deleted["confirmed"], deleted
        assert triggers(client) == []

        ask(
            client,
            "Create a trigger named build-on-issue that runs the agent with id platform-builder "
            "whenever a new issue is opened.",
        )
        assert triggers(client) == [], triggers(client)

        # Super Agent may decline that on its own. Ask it to try, to see what the tool answers.
        tried = ask(
            client,
            "Try it anyway: call the create trigger tool with target type agent and target id platform-builder, "
            "and tell me exactly what the tool answered.",
        )
        assert triggers(client) == [], triggers(client)
        assert "internal" in tried["content"].lower(), tried["content"]

        print()
        print(
            "Asked in words, Super Agent created a trigger for new issues, listed it, turned it off and "
            "deleted it after the deletion was confirmed. A trigger aimed at its own builder was not created: "
            "the tool answered that Manager specialists are internal."
        )


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
        agent_os.serve(app="super_agent_triggers:app", port=7777, reload=False)
