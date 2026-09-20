"""A generative model consults fixed Jev questions or proposes new questions."""

from typesafe_sdk import Noul

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.models.typesafe import JevTools

fixed = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[
        JevTools(
            questions={
                "urgent": Noul(
                    instructions="Does state.input describe work that is completely blocked?"
                )
            }
        )
    ],
    instructions="Use evaluate to assess the ticket, then explain the result. A probability is not a guarantee.",
)

dynamic = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[JevTools(allow_dynamic_questions=True)],
    instructions="Propose two independent yes/no hypotheses about the ticket's urgency. Call evaluate_questions with type='noul' and explicit instructions for each. The ticket is available at state.input. Explain the resulting probabilities.",
)

if __name__ == "__main__":
    fixed.print_response("Our production workspace is down")
    dynamic.print_response("Our production workspace is down")
