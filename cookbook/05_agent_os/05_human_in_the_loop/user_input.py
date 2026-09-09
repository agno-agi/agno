"""
Resolve multi-round user input for an AgentOS team
==================================================

A member agent collects a traveller name and trip preferences in two separate
tool calls. Each ``requires_user_input`` call pauses the team run. The client
fills the returned requirement schema and calls the team ``continue`` route
until the run completes.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/05_human_in_the_loop/user_input.py
Try: Run this file with --demo in another terminal
"""

import argparse
import json
from typing import Any

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create User Input Team
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
TEAM_ID = "trip-planning-team"
SESSION_ID = "user-input-demo"
USER_INPUTS: dict[str, str] = {
    "name": "Ada",
    "destination": "Kyoto",
    "budget": "2500 USD",
}


@tool(requires_user_input=True, user_input_fields=["name"])
def collect_name(name: str = "") -> str:
    """Record the traveller's name."""
    return f"Traveller: {name}"


@tool(
    requires_user_input=True,
    user_input_fields=["destination", "budget"],
)
def collect_preferences(destination: str = "", budget: str = "") -> str:
    """Record the traveller's destination and budget."""
    return f"Preferences: destination={destination}, budget={budget}"


db = SqliteDb(
    id="user-input-db",
    db_file="tmp/agent_os_hitl_user_input.db",
)

survey_agent = Agent(
    id="trip-survey-agent",
    name="Trip Survey Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[collect_name, collect_preferences],
    instructions=(
        "For every trip request, call collect_name first and then "
        "collect_preferences. The tools collect missing values; do not ask in chat."
    ),
)

trip_team = Team(
    id=TEAM_ID,
    name="Trip Planning Team",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[survey_agent],
    instructions=(
        "Delegate the request to the Trip Survey Agent and return the collected "
        "name, destination, and budget."
    ),
    store_member_responses=True,
)

agent_os = AgentOS(
    id="user-input-os",
    db=db,
    agents=[survey_agent],
    teams=[trip_team],
)
app = agent_os.get_app()


def provide_values(requirements: list[dict[str, Any]]) -> list[str]:
    """Fill both copies of each returned user-input schema."""
    provided: list[str] = []
    for requirement in requirements:
        tool_execution = requirement.get("tool_execution") or {}
        for schema in (
            requirement.get("user_input_schema") or [],
            tool_execution.get("user_input_schema") or [],
        ):
            for field in schema:
                name = field["name"]
                if name in USER_INPUTS:
                    field["value"] = USER_INPUTS[name]
                    if name not in provided:
                        provided.append(name)
        tool_execution["answered"] = True
    return provided


def run_demo() -> None:
    """Resolve each user-input pause through the team continuation route."""
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        response = client.post(
            f"/teams/{TEAM_ID}/runs",
            data={
                "message": "Plan a restaurant trip using the required survey.",
                "session_id": SESSION_ID,
                "stream": "false",
            },
        )
        response.raise_for_status()
        run = response.json()
        rounds = 0

        while run["status"] == "PAUSED":
            requirements = run.get("requirements") or []
            if not requirements:
                raise RuntimeError("The paused team run returned no requirements")
            provided = provide_values(requirements)
            rounds += 1
            print(f"Round {rounds}: provided {', '.join(provided)}")

            response = client.post(
                f"/teams/{TEAM_ID}/runs/{run['run_id']}/continue",
                data={
                    "requirements": json.dumps(requirements),
                    "session_id": run["session_id"],
                    "stream": "false",
                },
            )
            response.raise_for_status()
            run = response.json()
            if rounds > 3:
                raise RuntimeError("The team did not finish after three input rounds")

        if run["status"] != "COMPLETED":
            raise RuntimeError(f"Expected COMPLETED, got {run['status']}")
        if rounds < 2:
            raise RuntimeError(f"Expected two user-input pauses, observed {rounds}")
        print(f"Final status: {run['status']}")
        print(f"Result: {run.get('content')}")


# ---------------------------------------------------------------------------
# Run User Input Team
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
