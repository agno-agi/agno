"""Condition with CEL: check if previous step produced output.

Uses has_previous_step_content to skip processing when
a prior step returned nothing.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Condition, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Summarize the content from the previous step concisely.",
    markdown=True,
)

fallback = Agent(
    name="Fallback",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="No prior content was available. Ask the user to provide more details.",
    markdown=True,
)

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the given topic and provide key findings.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Has Previous Content Check",
    steps=[
        Step(name="Research", agent=researcher),
        Condition(
            name="Content Available",
            evaluator="has_previous_step_content",
            steps=[
                Step(name="Summarize", agent=summarizer),
            ],
            else_steps=[
                Step(name="Fallback", agent=fallback),
            ],
        ),
    ],
)

if __name__ == "__main__":
    workflow.print_response(input="What are the latest trends in renewable energy?")
