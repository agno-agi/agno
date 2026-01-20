from agno.agent import Agent
from agno.tools.email import EmailTools

receiver_email = "<receiver_email>"
sender_email = "<sender_email>"
sender_name = "<sender_name>"
sender_passkey = "<sender_passkey>"

# Example 1: Enable specific email functions
agent = Agent(
    tools=[
        EmailTools(
            receiver_email=receiver_email,
            sender_email=sender_email,
            sender_name=sender_name,
            sender_passkey=sender_passkey,
            enable_email_user=True,
        )
    ]
)

# Example 2: Enable all email functions
agent_all = Agent(
    tools=[
        EmailTools(
            receiver_email=receiver_email,
            sender_email=sender_email,
            sender_name=sender_name,
            sender_passkey=sender_passkey,
            all=True,
        )
    ]
)

# Test the agent
agent.print_response(
    "Send an email to the receiver with subject 'Test Email' and a friendly greeting message",
    markdown=True,
)
