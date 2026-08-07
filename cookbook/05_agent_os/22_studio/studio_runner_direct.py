"""
StudioRunnerTools called directly: list, run, and refusal semantics
===================================================================

The runner's tools are plain methods, so a platform can call them without a
wielding model. This example builds typed Agent, Team, and Workflow components,
lists them, runs an Agent by id, and shows the registry guard: a runner
constructed without the registry refuses to run a component whose stored
config references registry-backed resources, because the rebuild would
silently drop them.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_runner_direct.py
Try: pass registry=registry to the second runner and watch the refusal clear
"""

import json
from pathlib import Path
from typing import Any

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.run import RunContext
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioAccess, StudioAction, StudioTools
from agno.tools.studio_runner import StudioRunnerTools
from agno.tools.studio_schema import (
    AgentCreate,
    ComponentRef,
    ModelRef,
    StudioResult,
    TeamCreate,
    TeamWorkflowStep,
    ToolRef,
    WorkflowCreate,
)

# ---------------------------------------------------------------------------
# Create typed, published components for runner-only discovery
# ---------------------------------------------------------------------------

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)
DB_FILE = DB_DIR / "studio_runner_direct.db"
DB_FILE.unlink(missing_ok=True)

STUDIO_ADMIN_USER_ID = "studio-admin"


def authorize_studio_admin(
    run_context: RunContext,
    _access: StudioAccess,
    _action: StudioAction,
) -> bool:
    """Limit the administrative builder to the demo admin."""
    return run_context.user_id == STUDIO_ADMIN_USER_ID


db = SqliteDb(
    id="studio-runner-direct-db",
    db_file=str(DB_FILE),
)

registry = Registry(
    name="Direct Runner Registry",
    models=[OpenAIResponses(id="gpt-5.5")],
    tools=[CalculatorTools()],
    dbs=[db],
)

builder = StudioTools(
    registry=registry,
    db=db,
    authorize=authorize_studio_admin,
    default_model=ModelRef(
        id="gpt-5.5",
        provider="OpenAI",
        name="OpenAIResponses",
    ),
    teams=True,
    workflows=True,
)
admin_context = RunContext(
    run_id="seed-runner-components",
    session_id="seed-components",
    user_id=STUDIO_ADMIN_USER_ID,
)


def require_created(label: str, result: StudioResult[Any]) -> None:
    """Stop immediately if a typed Studio seed operation failed."""
    if not result.ok:
        raise RuntimeError(f"Studio could not seed {label}: {result}")


require_created(
    "Greeter",
    builder.create_agent(
        AgentCreate(
            component_id="greeter",
            name="Greeter",
            instructions="Greet the user in one short sentence.",
        ),
        save_as="published",
        _agno_run_context=admin_context,
    ),
)
require_created(
    "Calculator Agent",
    builder.create_agent(
        AgentCreate(
            component_id="calculator-agent",
            name="Calculator Agent",
            instructions="Solve arithmetic with the calculator tool.",
            tools=[ToolRef(kind="toolkit", name="calculator")],
        ),
        save_as="published",
        _agno_run_context=admin_context,
    ),
)
require_created(
    "Welcome Team",
    builder.create_team(
        TeamCreate(
            component_id="welcome-team",
            name="Welcome Team",
            instructions="Delegate the greeting to the Greeter.",
            members=[
                ComponentRef(
                    component_type="agent",
                    component_id="greeter",
                    version=1,
                )
            ],
        ),
        save_as="published",
        _agno_run_context=admin_context,
    ),
)
require_created(
    "Welcome Workflow",
    builder.create_workflow(
        WorkflowCreate(
            component_id="welcome-workflow",
            name="Welcome Workflow",
            steps=[
                TeamWorkflowStep(
                    kind="team",
                    step_id="welcome",
                    name="Welcome",
                    component_id="welcome-team",
                    version=1,
                )
            ],
        ),
        save_as="published",
        _agno_run_context=admin_context,
    ),
)


# ---------------------------------------------------------------------------
# Run them as plain methods
# ---------------------------------------------------------------------------


def main() -> None:
    runner = StudioRunnerTools(registry=registry, db=db)

    listing = json.loads(runner.list_agents())
    print("Agents in the platform database:")
    for row in listing["agents"]:
        print(" -", row["id"], "|", row["name"])
    print("Teams:", [row["id"] for row in json.loads(runner.list_teams())["teams"]])
    print(
        "Workflows:",
        [row["id"] for row in json.loads(runner.list_workflows())["workflows"]],
    )

    result = json.loads(
        runner.run_agent(
            "greeter",
            "Hello there.",
            RunContext(
                run_id="run-greeter", session_id="runner-demo", user_id="demo-user"
            ),
        )
    )
    print("Run status:", result["status"])
    print("Run content:", result["content"])

    # Without the registry, the tool-bearing component is refused: rebuilding
    # it would drop the calculator and run a silently degraded agent.
    registry_less = StudioRunnerTools(db=db)
    refusal = json.loads(registry_less.run_agent("calculator-agent", "What is 2 + 2?"))
    print("Registry-less refusal:", refusal["error"])


if __name__ == "__main__":
    main()
