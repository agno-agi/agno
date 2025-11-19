import asyncio

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow import WorkflowAgent
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


story_writer = Agent(
    name="story_writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are tasked with writing a 100 word story based on a given topic",
)

story_formatter = Agent(
    name="story_formatter",
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


async def main():
    """Async main function"""
    # ============================================================================
    # ASYNC STREAMING EXAMPLES
    # ============================================================================

    print("\n" + "=" * 80)
    print("FIRST CALL (ASYNC STREAMING): Tell me a story about a dog named Rocky")
    print("=" * 80)
    await workflow.aprint_response(
        "Tell me a story about a dog named Rocky",
        stream=True,
    )

    print("\n" + "=" * 80)
    print("SECOND CALL (ASYNC STREAMING): What was Rocky's personality?")
    print("=" * 80)
    await workflow.aprint_response("What was Rocky's personality?", stream=True)

    print("\n" + "=" * 80)
    print("THIRD CALL (ASYNC STREAMING): Now tell me a story about a cat named Luna")
    print("=" * 80)
    await workflow.aprint_response(
        "Tell me a story about a cat named Luna",
        stream=True,
    )

    print("\n" + "=" * 80)
    print("FOURTH CALL (ASYNC STREAMING): Compare Rocky and Luna")
    print("=" * 80)
    await workflow.aprint_response("Compare Rocky and Luna", stream=True)


if __name__ == "__main__":
    asyncio.run(main())
