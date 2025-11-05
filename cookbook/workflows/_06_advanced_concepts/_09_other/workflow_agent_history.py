from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="workflow_session")

agent = Agent(
    id="agent_001",
    model=OpenAIChat(id="gpt-5-mini"),
    add_history_to_context=True,
)
workflow = Workflow(
    session_id="test_session_002",
    steps=[Step(agent=agent)],
    db=db,
)
workflow.print_response(input="Hello, how are you?")
