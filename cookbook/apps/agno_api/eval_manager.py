"""Simple example creating a session and using the AgnoAPI with a SessionManager to expose it"""

from agno.agent import Agent
from agno.app.agno_api import AgnoAPI
from agno.app.agno_api.interfaces.playground import Playground
from agno.app.agno_api.managers.eval.eval import EvalManager
from agno.db.postgres.postgres import PostgresDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIChat

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5432/ai"
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
agno_client = AgnoAPI(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    app_id="basic-app",
    agents=[basic_agent],
    interfaces=[Playground()],
    managers=[EvalManager(db=db)],
)
app = agno_client.get_app()


if __name__ == "__main__":
    """ Run the Agno API App:
    Now you can interact with your eval runs using the API. Examples:
    - http://localhost:8001/evals/v1/evals
    - http://localhost:8001/evals/v1/evals/123
    - http://localhost:8001/evals/v1/evals?agent_id=123
    - http://localhost:8001/evals/v1/evals?limit=10&offset=0&sort_by=created_at&sort_order=desc
    """
    agno_client.serve(app="eval_manager:app", reload=True)
