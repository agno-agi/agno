"""
Repro for #10086 through AgentOS with a requires_confirmation tool.

Both the initial run and the continue use background=true + stream=true, which is
what AgentOS clients use for HITL over SSE. With add_history_to_context=True the
continue used to re-read the paused run as its own history and send the tool call
twice to the model.

Run the server:  .venvs/demo/bin/python libs/agno/agno/test.py
Run the client:  .venvs/demo/bin/python libs/agno/agno/test.py --demo
"""

import argparse
import json
from typing import Any, Dict, List

import httpx

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools import tool

BASE_URL = "http://localhost:7777"
AGENT_ID = "confirmation-agent"


@tool(requires_confirmation=True)
def restart_service(service: str) -> str:
    """Restart one service after the caller confirms the action."""
    return f"Restarted {service}"


db = SqliteDb(id="repro-db", db_file="/tmp/repro_agent_os.db")

agent = Agent(
    id=AGENT_ID,
    name="Confirmation Agent",
    # Chat Completions rejects an assistant tool_calls turn without a matching tool result,
    # which is what surfaces the duplicated history.
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    tools=[restart_service],
    add_history_to_context=True,
    instructions=(
        "When asked to restart a service, call restart_service immediately. "
        "Do not ask for confirmation in chat because the tool enforces it."
    ),
)

agent_os = AgentOS(id="repro-os", db=db, agents=[agent])
app = agent_os.get_app()


def drain_sse(client: httpx.Client, url: str, data: Dict[str, str]) -> Dict[str, Any]:
    """POST a streaming request, print event names, and return the run_id/session_id seen."""
    ids: Dict[str, Any] = {}
    with client.stream("POST", url, data=data) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event:"):
                print(f"  {line}")
            elif line.startswith("data:"):
                try:
                    payload = json.loads(line[len("data:") :].strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    for key in ("run_id", "session_id"):
                        if payload.get(key) and key not in ids:
                            ids[key] = payload[key]
                    if payload.get("event") == "RunError":
                        print(f"  RunError: {payload.get('content')}")
    return ids


def get_run(client: httpx.Client, run_id: str, session_id: str) -> Dict[str, Any]:
    response = client.get(f"/agents/{AGENT_ID}/runs/{run_id}", params={"session_id": session_id})
    response.raise_for_status()
    return response.json()


def confirm_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for pending_tool in tools:
        if pending_tool.get("requires_confirmation"):
            pending_tool["confirmed"] = True
    return tools


def run_demo() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        print("Starting run (background + stream)")
        ids = drain_sse(
            client,
            f"/agents/{AGENT_ID}/runs",
            {"message": "Restart the billing service.", "stream": "true", "background": "true"},
        )
        run = get_run(client, ids["run_id"], ids["session_id"])
        print(f"Status after run: {run['status']}")

        while run["status"] == "PAUSED":
            tools = confirm_tools(run.get("tools") or [])
            print("Continuing run (background + stream)")
            drain_sse(
                client,
                f"/agents/{AGENT_ID}/runs/{run['run_id']}/continue",
                {
                    "tools": json.dumps(tools),
                    "session_id": run["session_id"],
                    "stream": "true",
                    "background": "true",
                },
            )
            run = get_run(client, run["run_id"], run["session_id"])
            print(f"Status after continue: {run['status']}")

        print(f"Final status: {run['status']}")
        print(f"Content: {run.get('content')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Run the HTTP client against a running server.")
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, port=7777)
