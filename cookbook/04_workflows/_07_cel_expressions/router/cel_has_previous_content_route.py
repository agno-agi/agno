"""Router with CEL: route based on whether previous content exists.

Uses has_previous_step_content to choose between processing
existing results or starting fresh.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Step, Workflow
from agno.workflow.router import Router

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

refiner = Agent(
    name="Refiner",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Refine and improve the content from the previous step.",
    markdown=True,
)

creator = Agent(
    name="Creator",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Create new content from scratch based on the input.",
    markdown=True,
)

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the topic and provide initial findings.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Has Previous Content Router",
    steps=[
        Step(name="Research", agent=researcher),
        Router(
            name="Refine or Create",
            selector='has_previous_step_content ? "Refiner" : "Creator"',
            choices=[
                Step(name="Refiner", agent=refiner),
                Step(name="Creator", agent=creator),
            ],
        ),
    ],
)

if __name__ == "__main__":
    workflow.print_response(input="Explore the potential of nuclear fusion energy.")
