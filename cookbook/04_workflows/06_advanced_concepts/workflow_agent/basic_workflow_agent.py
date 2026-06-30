"""
Basic Workflow Agent
====================

Demonstrates using `WorkflowAgent` to decide when to execute workflow steps versus answer from history.
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow import WorkflowAgent
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

story_writer = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    instructions="You are tasked with writing a 100 word story based on a given topic",
)

story_formatter = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    instructions="You are tasked with breaking down a short story in prelogues, body and epilogue",
)


# ---------------------------------------------------------------------------
# Define Function Step
# ---------------------------------------------------------------------------
def add_references(step_input: StepInput):
    previous_output = step_input.previous_step_content

    if isinstance(previous_output, str):
        return previous_output + "\n\nReferences: https://www.agno.com"


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-5.2"), num_history_runs=4)

workflow = Workflow(
    name="Story Generation Workflow",
    description="A workflow that generates stories, formats them, and adds references",
    agent=workflow_agent,
    steps=[story_writer, story_formatter, add_references],
    db=PostgresDb(db_url),
)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
async def run_async_examples() -> None:
    print("\n" + "=" * 80)
    print("FIRST CALL (ASYNC): Tell me a story about a husky named Max")
    print("=" * 80)
    await workflow.aprint_response("Tell me a story about a husky named Max")

    print("\n" + "=" * 80)
    print("SECOND CALL (ASYNC): What was Max like?")
    print("=" * 80)
    await workflow.aprint_response("What was Max like?")

    print("\n" + "=" * 80)
    print("THIRD CALL (ASYNC): Now tell me about a cat named Luna")
    print("=" * 80)
    await workflow.aprint_response("Now tell me about a cat named Luna")

    print("\n" + "=" * 80)
    print("FOURTH CALL (ASYNC): Compare Max and Luna")
    print("=" * 80)
    await workflow.aprint_response("Compare Max and Luna")


async def run_async_streaming_examples() -> None:
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
        "Now tell me a story about a cat named Luna",
        stream=True,
    )

    print("\n" + "=" * 80)
    print("FOURTH CALL (ASYNC STREAMING): Compare Rocky and Luna")
    print("=" * 80)
    await workflow.aprint_response("Compare Rocky and Luna", stream=True)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("FIRST CALL: Tell me a story about a husky named Max")
    print("=" * 80)
    workflow.print_response("Tell me a story about a husky named Max")

    print("\n" + "=" * 80)
    print("SECOND CALL: What was Max like?")
    print("=" * 80)
    workflow.print_response("What was Max like?")

    print("\n" + "=" * 80)
    print("THIRD CALL: Now tell me about a cat named Luna")
    print("=" * 80)
    workflow.print_response("Now tell me about a cat named Luna")

    print("\n" + "=" * 80)
    print("FOURTH CALL: Compare Max and Luna")
    print("=" * 80)
    workflow.print_response("Compare Max and Luna")

    print("\n\n" + "=" * 80)
    print("STREAMING MODE EXAMPLES")
    print("=" * 80)

    print("\n" + "=" * 80)
    print("FIRST CALL (STREAMING): Tell me a story about a dog named Rocky")
    print("=" * 80)
    workflow.print_response("Tell me a story about a dog named Rocky", stream=True)

    print("\n" + "=" * 80)
    print("SECOND CALL (STREAMING): What was Rocky's personality?")
    print("=" * 80)
    workflow.print_response("What was Rocky's personality?", stream=True)

    print("\n" + "=" * 80)
    print("THIRD CALL (STREAMING): Now tell me a story about a cat named Luna")
    print("=" * 80)
    workflow.print_response("Now tell me about a cat named Luna", stream=True)

    print("\n" + "=" * 80)
    print("FOURTH CALL (STREAMING): Compare Rocky and Luna")
    print("=" * 80)
    workflow.print_response("Compare Rocky and Luna", stream=True)

    asyncio.run(run_async_examples())
    asyncio.run(run_async_streaming_examples())
