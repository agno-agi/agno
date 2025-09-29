"""Example showing how to use AgentOS with Supabase as our database provider"""

from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team

SUPABASE_PROJECT = getenv("SUPABASE_PROJECT")
SUPABASE_PASSWORD = getenv("SUPABASE_PASSWORD")

SUPABASE_DB_URL = (
    f"postgresql://postgres:{SUPABASE_PASSWORD}@db.{SUPABASE_PROJECT}:5432/postgres"
)

# Setup the Postgres database
db = PostgresDb(db_url=SUPABASE_DB_URL)

# Setup a basic agent and a basic team
agent = Agent(
    name="Basic Agent",
    id="basic-agent",
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)
team = Team(
    id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    enable_user_memories=True,
    members=[agent],
    debug_mode=True,
)

# Evals
evaluation = AccuracyEval(
    db=db,
    name="Calculator Evaluation",
    model=OpenAIChat(id="gpt-4o"),
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

if __name__ == "__main__":
    agent.run("What is the weather in Tokyo?")
    agent_os.serve(app="supabase_demo:app", reload=True)
