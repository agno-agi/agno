"""
Plivo Tools
=============================

Demonstrates plivo tools.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.plivo import PlivoTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


"""
Example showing how to use the Plivo Tools with Agno.

Requirements:
- Plivo Auth ID and Auth Token (get from https://cx.plivo.com)
- A Plivo phone number
- uv pip install plivo

Usage:
- Set the following environment variables:
    export PLIVO_AUTH_ID="your_auth_id"
    export PLIVO_AUTH_TOKEN="your_auth_token"

- Or provide them when creating the PlivoTools instance
"""


# Example 1: Enable specific Plivo functions
agent = Agent(
    name="Plivo Agent",
    instructions=[
        """You can help users by:
        - Sending SMS messages
        - Checking message history
        - getting call details
        """
    ],
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        PlivoTools(
            enable_send_sms=True,
            enable_get_call_details=True,
            enable_list_messages=True,
        )
    ],
    markdown=True,
)

# Example 2: Enable all Plivo functions
agent_all = Agent(
    name="Plivo Agent All",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[PlivoTools(all=True)],
    markdown=True,
)

# Example 3: Enable only SMS functionality
sms_agent = Agent(
    name="SMS Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        PlivoTools(
            enable_send_sms=True,
            enable_get_call_details=False,
            enable_list_messages=False,
        )
    ],
    markdown=True,
)

sender_phone_number = "+1234567890"
receiver_phone_number = "+1234567890"

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        f"Can you send an SMS saying 'Your package has arrived' to {receiver_phone_number} from {sender_phone_number}?"
    )
