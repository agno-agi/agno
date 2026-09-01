"""
Plivo Tools
=============================

Demonstrates the Plivo tools: send SMS, place calls, look up numbers, and review call/message history.

Requirements:
- Plivo Auth ID and Auth Token (get from https://cx.plivo.com)
- A Plivo phone number

Install:

    uv pip install plivo

Set the following environment variables (or pass them to PlivoTools directly):

    export PLIVO_AUTH_ID="your_auth_id"
    export PLIVO_AUTH_TOKEN="your_auth_token"
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.plivo import PlivoTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    name="Plivo Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[PlivoTools()],  # all functions are enabled by default
    markdown=True,
)

sender_phone_number = "+1234567890"
receiver_phone_number = "+1234567890"

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Look up carrier and line-type info for a number
    agent.print_response(f"Look up carrier info for {receiver_phone_number}")

    # Send an SMS
    agent.print_response(
        f"Send an SMS saying 'Your package has arrived' to {receiver_phone_number} from {sender_phone_number}"
    )

    # Place a phone call (answer_url must return Plivo XML)
    agent.print_response(
        f"Call {receiver_phone_number} from {sender_phone_number} using answer_url "
        "https://s3.amazonaws.com/static.plivo.com/answer.xml with answer_method GET"
    )

    # Review recent call history
    agent.print_response("Show my 5 most recent calls with their status and duration")

    # Check recent message history
    agent.print_response("List my 10 most recent messages")

    # Get details for a specific call
    agent.print_response("Get the details for my most recent call")
