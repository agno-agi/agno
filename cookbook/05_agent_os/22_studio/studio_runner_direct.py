"""
StudioRunnerTools called directly: list, run, and refusal semantics
===================================================================

The runner's tools are plain methods, so a platform can call them without a
wielding model. This example builds one component, lists it, runs it by id,
and shows the registry guard: a runner constructed without the registry
refuses to run a component whose stored config references registry-backed
resources, because the rebuild would silently drop them.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_runner_direct.py
Try: pass registry=registry to the second runner and watch the refusal clear
"""

import json
from pathlib import Path

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioTools
from agno.tools.studio_runner import StudioRunnerTools

# ---------------------------------------------------------------------------
# Create two components: one plain, one with registry-backed tools
# ---------------------------------------------------------------------------

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)
DB_FILE = DB_DIR / "studio_runner_direct.db"
DB_FILE.unlink(missing_ok=True)

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

builder = StudioTools(registry=registry, db=db, default_model_id="gpt-5.5")
builder.create_agent(
    name="Greeter",
    instructions="Greet the user in one short sentence.",
    model_id="gpt-5.5",
)
builder.create_agent(
    name="Calculator Agent",
    instructions="Solve arithmetic with the calculator tool.",
    model_id="gpt-5.5",
    tool_names=["calculator"],
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

    result = json.loads(runner.run_agent("greeter", "Hello there."))
    print("Run status:", result["status"])
    print("Run content:", result["content"])

    # Without the registry, the tool-bearing component is refused: rebuilding
    # it would drop the calculator and run a silently degraded agent.
    registry_less = StudioRunnerTools(db=db)
    refusal = json.loads(registry_less.run_agent("calculator-agent", "What is 2 + 2?"))
    print("Registry-less refusal:", refusal["error"])


if __name__ == "__main__":
    main()
