"""Simple example creating a session and using the AgentOS with a SessionManager to expose it"""

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.managers import EvalManager
from agno.db.postgres.postgres import PostgresDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIChat

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url=db_url,
    eval_table="eval_runs",
)

# Setup the agent
basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    enable_user_memories=True,
    markdown=True,
)

# Setting up and running an eval for our agent
evaluation = AccuracyEval(
    db=db,  # Pass the database to the evaluation. Results will be stored in the database.
    name="Calculator Evaluation",
    model=OpenAIChat(id="gpt-4o"),
    agent=basic_agent,
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
)
evaluation.run(print_results=True)

# Setup the Agno API App
agent_os = AgentOS(
    name="Example App: Eval Agent",
    description="Example app for basic agent with eval capabilities",
    os_id="eval-demo",
    agents=[basic_agent],
    apps=[EvalManager(db=db)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """ Run your AgentOS:
    Now you can interact with your eval runs using the API. Examples:
    - http://localhost:8001/eval/{id}/evals
    - http://localhost:8001/eval/{id}/evals/123
    - http://localhost:8001/eval/{id}/evals?agent_id=123
    - http://localhost:8001/eval/{id}/evals?limit=10&page=0&sort_by=created_at&sort_order=desc
    """
    agent_os.serve(app="eval_connector:app", reload=True)
