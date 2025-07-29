"""Example showing how to use AgentOS with JSON files as database"""

from agno.agent import Agent
from agno.db.json import JsonDb
from agno.eval.accuracy import AccuracyEval
from agno.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team

# Setup the JSON database
db = JsonDb(db_path="./agno_json_data")

# Setup the memory
memory = Memory(db=db)

# Setup a basic agent and a basic team
agent = Agent(
    name="JSON Demo Agent",
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

team = Team(
    team_id="basic-team",
    name="JSON Demo Team",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    members=[agent],
    debug_mode=True,
)

# Evaluation example
evaluation = AccuracyEval(
    db=db,
    name="JSON Demo Evaluation",
    model=OpenAIChat(id="gpt-4o"),
    agent=agent,
    input="What is 2 + 2?",
    expected_output="4",
    num_iterations=1,
)
# evaluation.run(print_results=True)

# Create the AgentOS instance
agent_os = AgentOS(
    description="Example app using JSON file database for simple deployments and demos",
    os_id="json-demo-app",
    agents=[agent],
    teams=[team],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="json_demo:app", reload=True)
