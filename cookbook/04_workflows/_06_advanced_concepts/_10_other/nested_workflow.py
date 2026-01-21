"""
Nested Workflow Example

This example demonstrates how to use a workflow as a step within another workflow.
This is useful for composing complex workflows from simpler, reusable sub-workflows.

In this example:
- We create an "inner" workflow that performs a simple research task
- We create an "outer" workflow that uses the inner workflow as one of its steps
- The outer workflow orchestrates multiple steps including the nested workflow
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from agno.workflow.types import StepInput, StepOutput
from agno.db.postgres import PostgresDb


def create_summary(step_input: StepInput) -> StepOutput:
    """A simple function step that summarizes the previous step's output"""
    previous_content = step_input.get_last_step_content()
    summary = f"Summary of research:\n{previous_content[:500]}..." if previous_content else "No content to summarize"
    return StepOutput(content=summary)


# Create a simple inner workflow that does research
research_agent = Agent(
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a research assistant. Provide concise, factual information.",
)

inner_workflow = Workflow(
    name="Research Workflow",
    description="A simple workflow that researches a topic",
    steps=[
        Step(name="research", agent=research_agent),
        Step(name="summary", executor=create_summary),
    ],
)

# Create the outer workflow that uses the inner workflow as a step
writer_agent = Agent(
    name="Writer Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a professional writer. Take the research provided and write a polished article.",
)

outer_workflow = Workflow(
    name="Research and Write Workflow",
    description="A workflow that researches a topic and then writes about it",
    steps=[
        # Use the inner workflow as a step
        Step(name="research_phase", workflow=inner_workflow),
        # Then write based on the research
        Step(name="writing_phase", agent=writer_agent),
    ],
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
)


if __name__ == "__main__":
    # Run the outer workflow
    print("Running nested workflow example...")
    print("=" * 50)

    result = outer_workflow.print_response(input="Tell me about the history of artificial intelligence", stream=True, stream_events=True)