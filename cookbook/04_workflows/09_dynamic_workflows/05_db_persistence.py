"""Dynamic Workflow - DB persistence and round-trip.

Show that a dynamic workflow's run output — including the full `executed_steps` trail —
persists to a database and round-trips correctly when the session is reloaded.

Demonstrates:
- attaching a database via `db=`
- `executed_steps` saved and reloaded via `Workflow.get_session(...)`
- the run's `step_results` and events round-trip too

Prerequisites:
    ./cookbook/scripts/run_pgvector.sh   # starts a local Postgres

Run:
    .venvs/demo/bin/python cookbook/04_workflows/09_dynamic_workflows/05_db_persistence.py
"""

from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.tools.hackernews import HackerNewsTools
from agno.workflow import DynamicWorkflowDriver, Workflow

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def main() -> None:
    driver = DynamicWorkflowDriver(
        model=OpenAIResponses(id="gpt-5.4"),
        instructions="Produce a short HN briefing on the user's topic. 1-2 spawns is plenty.",
        allowed_tools=[HackerNewsTools()],
        max_steps=3,
    )

    workflow = Workflow(
        name="DynamicPersistedBriefing",
        steps=driver,
        db=PostgresDb(session_table="workflow_session", db_url=DB_URL),
    )

    result = workflow.run(input="What is HN saying about open-source AI models?")

    print("\n=== Final Briefing ===")
    print(result.content)
    print("\n=== Dynamic Plan (in-memory result) ===")
    result.pretty_print_plan()

    # Round-trip: reload the session from the DB and pull the same run back out.
    print("\n=== Reloaded from DB ===")
    session = workflow.get_session(session_id=result.session_id)
    if session is None or not session.runs:
        print("Session not found or has no runs.")
        return

    reloaded = session.runs[-1]
    print(f"Reloaded run_id: {reloaded.run_id}")
    print(f"Reloaded executed_steps count: {len(reloaded.executed_steps)}")
    reloaded.pretty_print_plan()


if __name__ == "__main__":
    main()
