from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow import WorkflowAgent
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


# Create a WorkflowAgent that will decide when to run the workflow
workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-4o-mini"), num_history_runs=4)

# Create workflow with the WorkflowAgent
workflow = Workflow(
    name="Story Generation Workflow",
    description="A workflow that generates stories, formats them, and adds references",
    agent=workflow_agent,
    steps=[story_writer, story_formatter, add_references],
    db=PostgresDb(db_url),
    # debug_mode=True,
)

# ============================================================================
# STREAMING EXAMPLES
# ============================================================================

print("\n\n" + "=" * 80)
print("STREAMING MODE EXAMPLES")
print("=" * 80)

print("\n" + "=" * 80)
print("FIRST CALL (STREAMING): Tell me a story about a dog named Rocky")
print("=" * 80)
workflow.print_response(
    "Tell me a story about a dog named Rocky",
    stream=True,
)

print("\n" + "=" * 80)
print("SECOND CALL (STREAMING): What was Rocky's personality?")
print("=" * 80)
workflow.print_response("What was Rocky's personality?", stream=True)

print("\n" + "=" * 80)
print("THIRD CALL (STREAMING): Now tell me a story about a cat named Luna")
print("=" * 80)
workflow.print_response(
    "Now tell me a story about a cat named Luna",
    stream=True,
)

print("\n" + "=" * 80)
print("FOURTH CALL (STREAMING): Compare Rocky and Luna")
print("=" * 80)
workflow.print_response("Compare Rocky and Luna", stream=True)
