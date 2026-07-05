"""Example showing how to use AgentOS with a Turso database.

Turso is a from-scratch, SQLite-compatible database (the engine behind the
`pyturso` driver). TursoDb reuses the SQLite backend and only swaps in the
`sqlite+turso` SQLAlchemy dialect. This example uses a local Turso database file.

Requires: pip install "pyturso[sqlalchemy]"   (or: pip install "agno[turso]")
"""

from agno.agent import Agent
from agno.db.turso import TursoDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Setup the Turso database (local database file).
db = TursoDb(
    db_file="agno.db",
    session_table="sessions",
    eval_table="eval_runs",
    memory_table="user_memories",
    metrics_table="metrics",
)


# Setup a basic agent and a basic team
basic_agent = Agent(
    name="Basic Agent",
    id="basic-agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    update_memory_on_run=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)
team_agent = Team(
    id="basic-team",
    name="Team Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[basic_agent],
    debug_mode=True,
)

# Evals
evaluation = AccuracyEval(
    db=db,
    name="Calculator Evaluation",
    model=OpenAIResponses(id="gpt-5.5"),
    agent=basic_agent,
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
)
# evaluation.run(print_results=True)

agent_os = AgentOS(
    description="Example OS setup",
    agents=[basic_agent],
    teams=[team_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # NOTE: reload=False (single process). Turso (beta) is single-writer and does not
    # support multi-process access to the same database file yet, so the reloader's
    # second process would cause "database is locked" (tursodatabase/turso#769).
    agent_os.serve(app="turso_db:app", reload=False)
