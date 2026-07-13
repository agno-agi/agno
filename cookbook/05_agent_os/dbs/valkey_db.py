"""Example showing how to use AgentOS with Valkey as the database

Start Valkey locally with `./cookbook/scripts/run_valkey.sh`, or directly with docker:
`docker run --name my-valkey -p 6379:6379 -d valkey/valkey-bundle`
"""

from agno.agent import Agent
from agno.db.valkey import ValkeyDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Setup the Valkey database
db = ValkeyDb(
    session_table="sessions_new",
    metrics_table="metrics_new",
)

# Setup a basic agent and a basic team
agent = Agent(
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
team = Team(
    id="basic-team",
    name="Team Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[agent],
)

# Evals
evaluation = AccuracyEval(
    db=db,
    name="Calculator Evaluation",
    model=OpenAIResponses(id="gpt-5.5"),
    agent=agent,
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
)
# evaluation.run(print_results=True)

agent_os = AgentOS(
    description="Example OS setup",
    agents=[agent],
    teams=[team],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="valkey_db:app", reload=True)
