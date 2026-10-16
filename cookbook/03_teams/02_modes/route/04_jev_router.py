"""
Route Mode With a Jev Leader
============================

Demonstrates `mode=route` with Jev, TypeSafe's System One model, as the team leader.

Routing is a pick-one decision, which is what Jev is built for: it reads the request and
chooses a member and returns its confidence. It does not
write text, so nothing is added in front of the member's reply.

How the pieces map onto Jev:
- each member's name, role and description is one option
- the team's description and instructions are the routing guidance
- the user's message is handed to the chosen member word for word

Members need their own generative model: a member without one would inherit Jev from the team.

`min_confidence` decides what happens when Jev is not sure. With `fallback_member_id` the request
goes to that member; without it Jev abstains and the run returns an error.

Requirements:
- `pip install typesafe-sdk openai` (Python 3.10+)
- export TYPESAFE_API_KEY="your_api_key"   (https://console.typesafe.ai/keys)
- export OPENAI_API_KEY="your_api_key"
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.models.typesafe import Jev
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

billing_agent = Agent(
    name="Billing Agent",
    id="billing",
    role="Charges, refunds, invoices and payment methods",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=["You handle billing questions for an online store. Be brief."],
)

tech_agent = Agent(
    name="Tech Support Agent",
    id="tech-support",
    role="Bugs, outages, error messages and integrations",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=["You troubleshoot technical problems for an online store. Be brief."],
)

orders_agent = Agent(
    name="Orders Agent",
    id="orders",
    role="Order status, delivery, cancellations and returns",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=[
        "You handle order and delivery questions for an online store. Be brief."
    ],
)

general_agent = Agent(
    name="General Assistant",
    id="general",
    role="Anything that is not about billing, technical problems or orders",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=["You answer general questions for an online store. Be brief."],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Support Desk",
    mode=TeamMode.route,
    # Requests Jev is unsure about go to the general assistant
    model=Jev(mode="route", min_confidence=0.5, fallback_member_id="general"),
    determine_input_for_members=False,
    members=[billing_agent, tech_agent, orders_agent, general_agent],
    # Jev reads these as routing guidance. It reads literally, so state each rule outright.
    instructions=[
        "A message about being charged, even for an order, goes to billing.",
        "A message about a package that has not arrived goes to orders.",
    ],
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    requests = [
        "I was charged twice for order A-104.",
        "Tracking still says 'label created' after two weeks. Where is my desk?",
        "Checkout throws a 500 error whenever I apply a coupon.",
        "Do you have any tips for setting up a home office?",
    ]
    for request in requests:
        team.print_response(request, stream=True)
