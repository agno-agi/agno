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
from agno.workflow import Workflow, WorkflowAgent

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def main() -> None:
    agent = WorkflowAgent(
        model=OpenAIResponses(id="gpt-5.4"),
        instructions="Produce a short HN briefing on the user's topic. 1-2 spawns is plenty.",
        allowed_tools=[HackerNewsTools()],
        max_steps=3,
    )

    workflow = Workflow(
        name="DynamicPersistedBriefing",
        agent=agent,
        db=PostgresDb(session_table="workflow_session", db_url=DB_URL),
    )

    # Run the workflow with pretty CLI output (spawn panels live, plan at end).
    workflow.print_response(
        input="What is HN saying about open-source AI models?",
        stream=True,
        stream_events=True,
    )

    # Round-trip: reload the latest session from the DB and pull the run back out.
    # This proves executed_steps / step_results / step_executor_runs all persist.
    print("\n=== Reloaded from DB ===")
    if workflow._workflow_session is None or not workflow._workflow_session.runs:
        print("No session in memory to reload.")
        return

    session_id = workflow._workflow_session.session_id
    session = workflow.get_session(session_id=session_id)
    if session is None or not session.runs:
        print("Session not found or has no runs.")
        return

    reloaded = session.runs[-1]
    print(f"Reloaded run_id: {reloaded.run_id}")
    print(f"Reloaded executed_steps count: {len(reloaded.executed_steps)}")
    for rec in reloaded.executed_steps:
        output_preview = (rec.output_content or "").strip().replace("\n", " ")
        if len(output_preview) > 80:
            output_preview = output_preview[:77] + "..."
        print(f"  [{rec.iteration}] {rec.role}: {output_preview}")


if __name__ == "__main__":
    main()
