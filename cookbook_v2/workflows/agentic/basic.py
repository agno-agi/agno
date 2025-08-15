from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


story_writer = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are tasked with writing a 100 word story based on a given topic",
)

story_formatter = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are tasked with breaking down a short story in prelogues, body and epilogue",
)


def add_references(step_input: StepInput):
    """Add references to the story"""

    previous_output = step_input.previous_step_content

    if isinstance(previous_output, str):
        return previous_output + "\n\nReferences: https://www.agno.com"


workflow_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are tasked with chatting to the user",
    db=PostgresDb(db_url),
    add_history_to_context=True,
)

workflow = Workflow(
    agent=workflow_agent,
    steps=[story_writer, story_formatter, add_references],
    session_id="workflow_session",
    db=PostgresDb(db_url),
)


workflow.print_response("Tell me a story about a husky names Max")
workflow.print_response("What was Max like?")
