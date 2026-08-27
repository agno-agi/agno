"""
Pass per-request dependencies through AgentOS
=============================================

AgentOS accepts a JSON ``dependencies`` form field on run requests and passes
the values into the agent's instruction templates. The client supplies a robot
name for one request and verifies that the served agent used it.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/06_customize/dependencies.py
Try: Run this file with --demo in another terminal
"""

import argparse
import json

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Dependency-Aware AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "dependency-aware-agent"

db = SqliteDb(
    id="dependencies-db",
    db_file="tmp/agent_os_dependencies.db",
)

story_agent = Agent(
    id=AGENT_ID,
    name="Dependency-Aware Story Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=(
        "Write exactly one sentence about a robot named {robot_name}. "
        "The sentence must contain that exact name."
    ),
)

agent_os = AgentOS(
    id="dependencies-os",
    db=db,
    agents=[story_agent],
)
app = agent_os.get_app()


def run_demo() -> None:
    """Send one dependency payload through the AgentOS run endpoint."""
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        response = client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": "Write the robot story.",
                "session_id": "dependencies-demo",
                "dependencies": json.dumps({"robot_name": "Anna"}),
                "stream": "false",
            },
        )
        response.raise_for_status()
        run = response.json()
        content = str(run.get("content"))
        if run["status"] != "COMPLETED":
            raise RuntimeError(f"Expected COMPLETED, got {run['status']}")
        if "Anna" not in content:
            raise RuntimeError("The model response did not use the dependency")
        print(f"Final status: {run['status']}")
        print(f"Result: {content}")


# ---------------------------------------------------------------------------
# Run Dependency-Aware AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the HTTP client against a server already listening on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, port=7777)
