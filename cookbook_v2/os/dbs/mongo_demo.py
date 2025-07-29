"""Example showing how to use AgentOS with a Mongo database"""

from agno.agent import Agent
from agno.db.mongo import MongoDb
from agno.eval.accuracy import AccuracyEval
from agno.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team

# Setup the Mongo database
db = MongoDb(
    db_url="mongodb://localhost:27017",
    session_collection="sessions",
    eval_collection="eval_runs",
    user_memory_collection="user_memories",
    metrics_collection="metrics",
)

# Setup the memory
memory = Memory(db=db)

# Setup a basic agent and a basic team
basic_agent = Agent(
    name="Basic Agent",
    agent_id="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_messages=True,
    num_history_runs=3,
    add_datetime_to_instructions=True,
    markdown=True,
)
basic_team = Team(
    team_id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    members=[basic_agent],
    debug_mode=True,
)

# Evals
evaluation = AccuracyEval(
    db=db,
    name="Calculator Evaluation",
    model=OpenAIChat(id="gpt-4o"),
    agent=basic_agent,
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
)
# evaluation.run(print_results=True)

agent_os = AgentOS(
    description="Example app for basic agent with playground capabilities",
    os_id="basic-app",
    agents=[basic_agent],
    teams=[basic_team],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="mongo_demo:app", reload=True)
