"""
Nested Workflow with Condition

Demonstrates using a workflow (containing a Condition step) as a step
in an outer workflow. The inner workflow decides whether content needs
fact-checking before passing results to the outer workflow's writer.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.workflow import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def needs_fact_check(step_input: StepInput) -> bool:
    """Check if the previous step's content mentions statistics or numbers."""
    prev = step_input.previous_step_content or ""
    return any(char.isdigit() for char in prev)


def format_for_writer(step_input: StepInput) -> StepOutput:
    """Pass content through for the outer workflow's writer step."""
    prev = step_input.previous_step_content or step_input.input
    return StepOutput(content=prev)


# --- Inner workflow: research with conditional fact-checking ---
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Research the topic. Include specific dates and numbers where relevant.",
)

fact_checker = Agent(
    name="Fact Checker",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Verify the facts in the provided text. Correct any inaccuracies.",
)

inner_workflow = Workflow(
    name="Research with Fact Check",
    description="Researches a topic and conditionally fact-checks the results",
    steps=[
        Step(name="research", agent=researcher),
        Condition(
            name="fact_check_gate",
            description="Fact-check if content contains numbers",
            evaluator=needs_fact_check,
            steps=[Step(name="fact_check", agent=fact_checker)],
            else_steps=[Step(name="pass_through", executor=format_for_writer)],
        ),
    ],
)

# --- Outer workflow ---
writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Write a polished paragraph from the research provided.",
)

outer_workflow = Workflow(
    name="Research, Check, and Write",
    description="Researches, conditionally fact-checks, then writes",
    steps=[
        Step(name="research_phase", workflow=inner_workflow),
        Step(name="writing_phase", agent=writer),
    ],
)


if __name__ == "__main__":
    outer_workflow.print_response(
        input="What are the key milestones in space exploration?",
        stream=True,
    )
