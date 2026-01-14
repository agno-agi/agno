from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.twilio import TwilioTools

"""
Example showing how to use the Twilio Tools with Agno.

Requirements:
- Twilio Account SID and Auth Token (get from console.twilio.com)
- A Twilio phone number
- pip install twilio

Usage:
- Set the following environment variables:
    export TWILIO_ACCOUNT_SID="your_account_sid"
    export TWILIO_AUTH_TOKEN="your_auth_token"

- Or provide them when creating the TwilioTools instance
"""


# Example 1: Enable specific Twilio functions
agent = Agent(
    name="Twilio Agent",
    instructions=[
        """You can help users by:
        - Sending SMS messages
        - Checking message history
        - getting call details
        """
    ],
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        TwilioTools(
            enable_send_sms=True,
            enable_get_call_details=True,
            enable_list_messages=True,
        )
    ],
    markdown=True,
)

# Example 2: Enable all Twilio functions
agent_all = Agent(
    name="Twilio Agent All",
    model=OpenAIChat(id="gpt-4o"),
    tools=[TwilioTools(all=True)],
    markdown=True,
)

# Example 3: Enable only SMS functionality
sms_agent = Agent(
    name="SMS Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        TwilioTools(
            enable_send_sms=True,
            enable_get_call_details=False,
            enable_list_messages=False,
        )
    ],
    markdown=True,
)

sender_phone_number = "+1234567890"
receiver_phone_number = "+1234567890"

agent.print_response(
    f"Can you send an SMS saying 'Your package has arrived' to {receiver_phone_number} from {sender_phone_number}?"
)
