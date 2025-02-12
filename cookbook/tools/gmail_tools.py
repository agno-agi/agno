"""
Gmail Agent that can read, draft and send emails using the Gmail.
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.gmail import GmailTools
from datetime import datetime, timedelta
agent = Agent(
    name="Gmail Agent",
    model=Gemini(id="gemini-2.0-flash-exp"),
    tools=[GmailTools()],
    description="You are an expert Gmail Agent that can read, draft and send emails using the Gmail.",
    instructions=[
        "Based on user query, you can read, draft and send emails using Gmail.",
        "While showing email contents, you can summarize the email contents, extract key details and dates.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
    show_tool_calls=False,
    debug_mode=True,
)

# agent.print_response(
#     "summarize my last 5 emails with dates and key details, regarding ai agents",
#     markdown=True,
#     stream=True,
# )

tool = GmailTools(
    credentials_path="storage/credentials.json",
)



# print(tool.get_emails_by_context(context="Security", count=5))

thread_id = "194fa616c1f1aa92"
message_id = "CAPe88YDTC4sgdVuiVXR6y7xx8T4tRDi90JacwM9=e7WeSSGkig@mail.gmail.com"
resp = tool.send_email_reply(
    thread_id=thread_id,
    message_id=message_id,
    to="willemcarel@gmail.com",
    subject="Re: Security",
    body="Hello, I am a security agent. I am here to help you with your security needs.",
    cc="",
)


# resp = tool.get_latest_emails(count=1)
print(resp)