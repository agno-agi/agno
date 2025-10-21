"""
Gmail Agent that can read, draft and send emails using the Gmail.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.gmail import GmailTools
from pydantic import BaseModel, Field


class FindEmailOutput(BaseModel):
    message_id: str = Field(..., description="The message id of the email")
    thread_id: str = Field(..., description="The thread id of the email")
    references: str = Field(..., description="The references of the email")
    in_reply_to: str = Field(..., description="The in-reply-to of the email")
    subject: str = Field(..., description="The subject of the email")
    body: str = Field(..., description="The body of the email")


# Example 1: Include specific Gmail functions for reading only
read_only_agent = Agent(
    name="Gmail Reader Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            include_tools=[
                "search_emails",
                "get_emails_by_thread",
                "mark_email_as_read",
                "mark_email_as_unread",
            ]
        )
    ],
    description="You are a Gmail reading specialist that can search and read emails.",
    instructions=[
        "You can search and read Gmail messages but cannot send or draft emails.",
        "You can mark emails as read or unread for processing workflows.",
        "Summarize email contents and extract key details and dates.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
    output_schema=FindEmailOutput,
)

# Example 2: Exclude dangerous functions (sending emails)
safe_gmail_agent = Agent(
    name="Safe Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(exclude_tools=["send_email", "send_email_reply"])],
    description="You are a Gmail agent with safe operations only.",
    instructions=[
        "You can read and draft emails but cannot send them.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
    output_schema=FindEmailOutput,
)

# Example 3: Full Gmail functionality (default)
agent = Agent(
    name="Full Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools()],
    description="You are an expert Gmail Agent that can read, draft and send emails using Gmail.",
    instructions=[
        "Based on user query, you can read, draft and send emails using Gmail.",
        "While showing email contents, you can summarize the email contents, extract key details and dates.",
        "Show the email contents in a structured markdown format.",
        "Attachments can be added to the email",
        "When you need to modify an email, make sure to find its message_id and thread_id in order to do modificaiton operations.",
    ],
    markdown=True,
    output_schema=FindEmailOutput,
)

# Example 1: Find the last email from a specific sender
email = "<replace_with_email_address>"
response = agent.print_response(
    f"Find the last email from {email} along with the message id, references and in-reply-to",
    markdown=True,
    stream=True,
    output_schema=FindEmailOutput,
)

# Example 2: Mark an email as read/unread (useful for processing workflows)
# Note: You would typically get the message_id from a search operation first

# Mark as read (removes UNREAD label)
agent.print_response(
    f"""Mark the last email received from {email} as unread.""",
    markdown=True,
    stream=True,
)

# Example 3: Send a new email with attachments
# agent.print_response(
#     f"""Send an email to {email} with subject 'Subject'
#     and body 'Body' and Attach the file 'tmp/attachment.pdf'""",
#     markdown=True,
#     stream=True,
# )
