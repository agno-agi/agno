"""A Jev classification step followed by a generative explanation step."""

from typesafe_sdk import Choice

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.models.typesafe import Jev
from agno.workflow import Step, Workflow

classifier = Agent(
    model=Jev(
        questions={
            "queue": Choice(
                instructions="Choose the support queue for state.input.",
                criteria={
                    "billing": "Payments and refunds",
                    "technical": "Bugs and outages",
                },
            ),
        }
    )
)
writer = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Explain which support queue the classification selected and suggest what details to include in the ticket.",
)

workflow = Workflow(
    name="Ticket triage",
    steps=[
        Step(name="Classify", agent=classifier),
        Step(name="Explain next steps", agent=writer),
    ],
)

if __name__ == "__main__":
    workflow.print_response("I was charged twice for my subscription")
