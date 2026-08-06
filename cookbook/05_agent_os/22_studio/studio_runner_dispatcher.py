"""
Dispatch Studio-built components from a runner-only Agent
=========================================================

StudioRunnerTools is the dispatch half of the Studio: list the components in
the platform database and run one by id. It carries no create/edit/delete
surface, so a router or team lead can hand work to built components without
holding the Studio's mutation tools. Runs execute as the current user, keep
one session per component per conversation, and relay PAUSED results.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_runner_dispatcher.py
Try: ask the dispatcher to run the same component twice and compare session ids
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.studio import StudioTools
from agno.tools.studio_runner import StudioRunnerTools

# ---------------------------------------------------------------------------
# Create a component with StudioTools
# ---------------------------------------------------------------------------

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)
DB_FILE = DB_DIR / "studio_runner.db"
DB_FILE.unlink(missing_ok=True)

db = SqliteDb(
    id="studio-runner-db",
    db_file=str(DB_FILE),
)

registry = Registry(
    name="Runner Registry",
    models=[OpenAIResponses(id="gpt-5.5")],
    dbs=[db],
)

builder = StudioTools(registry=registry, db=db, default_model_id="gpt-5.5")
builder.create_agent(
    name="Haiku Writer",
    instructions="Answer with a single haiku.",
    model_id="gpt-5.5",
)

# ---------------------------------------------------------------------------
# Run it from a runner-only Agent
# ---------------------------------------------------------------------------

dispatcher = Agent(
    name="Dispatcher",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[StudioRunnerTools(registry=registry, db=db)],
    instructions="Discover what exists, then delegate the request to the right component.",
    db=db,
    markdown=True,
)


def main() -> None:
    dispatcher.print_response("Have the haiku writer produce a haiku about databases.")


if __name__ == "__main__":
    main()
