"""
Nested Workflow with Router

Demonstrates using a workflow (containing a Router step) as a step
in an outer workflow. The inner workflow routes to different specialist
agents based on the topic, then the outer workflow polishes the output.
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.workflow import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow


def topic_router(step_input: StepInput) -> List[Step]:
    """Route to a specialist based on keywords in the input."""
    text = (step_input.input or "").lower()

    if any(kw in text for kw in ["code", "programming", "software", "api"]):
        return [Step(name="tech_research", agent=tech_specialist)]
    elif any(kw in text for kw in ["history", "war", "ancient", "century"]):
        return [Step(name="history_research", agent=history_specialist)]
    else:
        return [Step(name="general_research", agent=general_specialist)]


# --- Specialist agents ---
tech_specialist = Agent(
    name="Tech Specialist",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You are a technology expert. Provide detailed technical explanations.",
)

history_specialist = Agent(
    name="History Specialist",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You are a historian. Provide detailed historical context and analysis.",
)

general_specialist = Agent(
    name="General Specialist",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You are a general knowledge expert. Provide clear, informative answers.",
)

# --- Inner workflow: routed research ---
inner_workflow = Workflow(
    name="Routed Research",
    description="Routes to the right specialist based on the topic",
    steps=[
        Router(
            name="specialist_router",
            selector=topic_router,
            choices=[
                Step(name="tech_research", agent=tech_specialist),
                Step(name="history_research", agent=history_specialist),
                Step(name="general_research", agent=general_specialist),
            ],
        ),
    ],
)

# --- Outer workflow ---
editor = Agent(
    name="Editor",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You are an editor. Polish and improve the specialist's research into a clear article.",
)

outer_workflow = Workflow(
    name="Smart Research and Edit",
    description="Routes to the right specialist, then edits the result",
    steps=[
        Step(name="research_phase", workflow=inner_workflow),
        Step(name="editing_phase", agent=editor),
    ],
)


if __name__ == "__main__":
    outer_workflow.print_response(
        input="Explain how REST APIs work and best practices for designing them",
        stream=True,
    )
