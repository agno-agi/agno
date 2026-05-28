"""
Workflow Agent With Condition
=============================

Demonstrates using `WorkflowAgent` together with a conditional step in the workflow graph.
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow import WorkflowAgent
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

story_writer = Agent(
    name="Story Writer",
    model=OpenAIChat(id="gpt-5.2"),
    instructions="You are tasked with writing a 100 word story based on a given topic",
)

story_editor = Agent(
    name="Story Editor",
    model=OpenAIChat(id="gpt-5.2"),
    instructions="Review and improve the story's grammar, flow, and clarity",
)

story_formatter = Agent(
    name="Story Formatter",
    model=OpenAIChat(id="gpt-5.2"),
    instructions="Break down the story into prologue, body, and epilogue sections",
)


# ---------------------------------------------------------------------------
# Define Functions
# ---------------------------------------------------------------------------
def needs_editing(step_input: StepInput) -> bool:
    story = step_input.previous_step_content or ""
    word_count = len(story.split())
    return word_count > 50 or any(punct in story for punct in ["!", "?", ";", ":"])


def add_references(step_input: StepInput):
    previous_output = step_input.previous_step_content
    if isinstance(previous_output, str):
        return previous_output + "\n\nReferences: https://www.agno.com"


# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
write_step = Step(
    name="write_story",
    description="Write initial story",
    agent=story_writer,
)

edit_step = Step(
    name="edit_story",
    description="Edit and improve the story",
    agent=story_editor,
)

format_step = Step(
    name="format_story",
    description="Format the story into sections",
    agent=story_formatter,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow_agent = WorkflowAgent(model=OpenAIChat(id="gpt-5.2"), num_history_runs=4)

workflow = Workflow(
    name="Story Generation with Conditional Editing",
    description="A workflow that generates stories, conditionally edits them, formats them, and adds references",
    agent=workflow_agent,
    steps=[
        write_step,
        Condition(
            name="editing_condition",
            description="Check if story needs editing",
            evaluator=needs_editing,
            steps=[edit_step],
        ),
        format_step,
        add_references,
    ],
    db=PostgresDb(db_url),
)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
async def main() -> None:
    print("\n" + "=" * 80)
    print("WORKFLOW WITH CONDITION - ASYNC STREAMING")
    print("=" * 80)

    print("\n" + "=" * 80)
    print("FIRST CALL: Tell me a story about a brave knight")
    print("=" * 80)
    await workflow.aprint_response(
        "Tell me a story about a brave knight",
        stream=True,
    )

    print("\n" + "=" * 80)
    print("SECOND CALL: What was the knight's name?")
    print("=" * 80)
    await workflow.aprint_response(
        "What was the knight's name?",
        stream=True,
    )

    print("\n" + "=" * 80)
    print("THIRD CALL: Now tell me about a cat")
    print("=" * 80)
    await workflow.aprint_response(
        "Now tell me about a cat",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
