"""Example showing evals with AgentOS - both as hooks and standalone evaluations"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.eval.accuracy import AccuracyEval
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools.calculator import CalculatorTools

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Create evals that will run as hooks
agent_eval = AccuracyEval(
    input="What is 2+2?",
    expected_output="4",
    db=db,
    telemetry=False,
)

team_eval = AccuracyEval(
    input="What is 5+5?",
    expected_output="10",
    db=db,
    telemetry=False,
)


async def benchmark_func():
    return sum(range(1000))


performance_eval = PerformanceEval(
    func=benchmark_func,
    db=db,
    telemetry=False,
)

# Setup agent with evals as post_hooks
basic_agent = Agent(
    id="basic-agent",
    name="Calculator Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    markdown=True,
    instructions="You are an assistant that can answer arithmetic questions. Always use the Calculator tools you have.",
    tools=[CalculatorTools()],
    post_hooks=[
        agent_eval,
        performance_eval,
    ],  # Evals run automatically after each agent execution
)

# Setup team with eval as post_hook
basic_team = Team(
    name="Basic Team",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    members=[basic_agent],
    post_hooks=[team_eval],  # Eval runs automatically after each team execution
)

# You can also run standalone evaluations
standalone_eval = AccuracyEval(
    db=db,
    name="Standalone Evaluation",
    model=OpenAIChat(id="gpt-4o"),
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
    agent=basic_agent,
)
# standalone_eval.run(print_results=True)

# Setup the Agno API App
agent_os = AgentOS(
    description="Example app for basic agent with eval capabilities",
    id="eval-demo",
    agents=[basic_agent],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """ Run your AgentOS:
    Now you can interact with your eval runs using the API. Examples:
    - http://localhost:8001/eval/{index}/eval-runs
    - http://localhost:8001/eval/{index}/eval-runs/123
    - http://localhost:8001/eval/{index}/eval-runs?agent_id=123
    - http://localhost:8001/eval/{index}/eval-runs?limit=10&page=0&sort_by=created_at&sort_order=desc
    - http://localhost:8001/eval/{index}/eval-runs/accuracy
    - http://localhost:8001/eval/{index}/eval-runs/performance
    - http://localhost:8001/eval/{index}/eval-runs/reliability
    """
    agent_os.serve(app="evals_demo:app", reload=True)
