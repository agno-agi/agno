"""Example showing how to use AgentOS with a Firestore database"""

from agno.agent import Agent
from agno.db.firestore import FirestoreDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team

PROJECT_ID = "agno-os-test"

# Setup the Firestore database
db = FirestoreDb(
    project_id=PROJECT_ID,
    session_collection="sessions",
    eval_collection="eval_runs",
    memory_collection="user_memories",
    metrics_collection="metrics",
    knowledge_collection="knowledge",
)

# Setup a basic agent and a basic team
basic_agent = Agent(
    name="Basic Agent",
    id="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)
basic_team = Team(
    id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_user_memories=True,
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
    description="Example app for basic agent with Firestore database capabilities",
    id="firestore-app",
    agents=[basic_agent],
    teams=[basic_team],
)
app = agent_os.get_app()

if __name__ == "__main__":
    basic_agent.run("Please remember I really like French food")
    agent_os.serve(app="firestore_demo:app", reload=True)
