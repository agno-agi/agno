"""Jev selects one member; that member writes the answer.

Use Jev for the routing decision and reserve the generative model for the
selected specialist's response. The original request reaches that member
unchanged, with no generative leader or synthesis call.

Requires typesafe-sdk, openai, TYPESAFE_API_KEY, and OPENAI_API_KEY.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.models.typesafe import Jev
from agno.team import Team

billing = Agent(
    id="billing",
    name="Billing",
    role="Handle payment, subscription and refund questions",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)
technical = Agent(
    id="technical",
    name="Technical Support",
    role="Handle outages, bugs and configuration issues",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

team = Team(
    model=Jev(mode="route"),
    mode="route",
    determine_input_for_members=False,
    members=[billing, technical],
    instructions="Route duplicate charges and subscription problems to Billing. Route login failures and outages to Technical Support.",
)

if __name__ == "__main__":
    team.print_response(
        "I was charged twice this month. What should I do?", stream=True
    )
    team.print_response("The submit button is not visible", stream=True)

# Optional policy: Jev(mode="route", min_confidence=0.75, fallback_member_id="technical").
# Without a fallback, low confidence produces an error run and dispatches nobody.
