"""
Router With a Jev Classifier
============================

Demonstrates a Jev classification step feeding a Router selector.

Jev, TypeSafe's System One model, does not write text: it fills an `output_schema` with typed
judgments. Classify the
input once, then let plain code branch on the result. The selector below reads a pydantic
object, not prose, so there is nothing to parse and no keyword list to maintain.

The same typed result works as a `Condition` evaluator: `return triage.is_urgent`.

Requirements:
- `pip install typesafe-sdk openai` (Python 3.10+)
- export TYPESAFE_API_KEY="your_api_key"
- export OPENAI_API_KEY="your_api_key"
"""

from typing import Annotated, List, Literal

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.models.typesafe import Jev, JevField
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel
from typesafe_sdk import Choice, Noul
from rich.pretty import pprint
from agno.utils.pprint import pprint_run_response

# ---------------------------------------------------------------------------
# Define the Classification
# ---------------------------------------------------------------------------


class Triage(BaseModel):
    kind: Annotated[
        Literal["bug_report", "feature_request", "question"],
        JevField(
            Choice(
                instructions="What kind of message is state.input?",
                criteria={
                    "bug_report": "Something is broken or behaves wrongly",
                    "feature_request": "Asks for something the product does not do yet",
                    "question": "Asks how to do something the product already supports",
                },
            )
        ),
    ]
    is_urgent: Annotated[
        bool,
        JevField(
            Noul(
                instructions="Does the message say that work is blocked or that time is short?"
            ),
            threshold=0.7,
        ),
    ]


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

classifier = Agent(name="Classifier", model=Jev(), output_schema=Triage)

bug_agent = Agent(
    name="Bug Triager",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Write a short bug ticket: title, steps to reproduce, expected and actual behaviour.",
)

feature_agent = Agent(
    name="Product Analyst",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Restate the feature request as a one-paragraph user story with acceptance criteria.",
)

answer_agent = Agent(
    name="Support Writer",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Answer the customer's question in a few friendly sentences.",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------


def specialist(agent: Agent):
    """An agent step receives the previous step's output as its message. These steps come right
    after the classifier, so they run their agent on the original message instead and use the
    classification only to flag urgency."""

    def run_specialist(step_input: StepInput) -> StepOutput:
        triage = step_input.previous_step_content
        urgent = isinstance(triage, Triage) and triage.is_urgent
        message = f"[URGENT] {step_input.input}" if urgent else str(step_input.input)
        return StepOutput(content=agent.run(message).content)

    return run_specialist


classify = Step(name="classify", agent=classifier)
file_bug = Step(name="file_bug", executor=specialist(bug_agent))
log_feature = Step(name="log_feature", executor=specialist(feature_agent))
answer_question = Step(name="answer_question", executor=specialist(answer_agent))

ROUTES = {
    "bug_report": file_bug,
    "feature_request": log_feature,
    "question": answer_question,
}


# ---------------------------------------------------------------------------
# Define Router Selector
# ---------------------------------------------------------------------------
def route_by_triage(step_input: StepInput) -> List[Step]:
    triage = step_input.previous_step_content
    if not isinstance(triage, Triage):
        return [answer_question]
    pprint(triage)
    return [ROUTES[triage.kind]]


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Support Intake",
    description="Classify the message with Jev, then hand it to the matching specialist",
    steps=[
        classify,
        Router(
            name="route_by_kind",
            selector=route_by_triage,
            choices=[file_bug, log_feature, answer_question],
            description="Branches on the classification from the previous step",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for message in (
        "Exporting to CSV crashes the app every time, and I need the report for a meeting in an hour.",
        "It would be great if dashboards could be shared with people outside my team.",
    ):
        pprint({"input": message})
        response = workflow.run(input=message)
        pprint_run_response(response)
