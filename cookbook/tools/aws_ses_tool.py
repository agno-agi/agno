from agno.agent import Agent
from agno.tools.aws_ses import AWSSESTool

receiver_email = "<receiver_email>"
sender_email = "<sender_email>"
sender_name = "<sender_name>"
region_name = "<asw_region_name>"
agent = Agent(
    tools=[
        AWSSESTool(
            receiver_email=receiver_email,
            sender_email=sender_email,
            sender_name=sender_name,
            region_name=region_name,
        )
    ]
)

agent.print_response(
    "Send an email to the receiver_email with the subject hello and body  hello world."
)
