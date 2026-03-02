"""
Gmail Tools - Basic Configuration
==================================
Shows how to configure GmailTools with different permission levels:
read-only, safe (no sending), label management, and full access.

For agentic use-case examples, see:
- gmail_daily_digest.py      - Summarize today's emails into a structured digest
- gmail_inbox_triage.py      - Classify unread emails and apply labels
- gmail_draft_reply.py       - Read thread context and draft replies
- gmail_followup_tracker.py  - Find unanswered sent emails and draft follow-ups
- gmail_invoice_extractor.py - Extract structured data from invoices/receipts

Setup: See GmailTools module docstring for Google OAuth credential setup.
Run: pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools

# Example 1: Read-only (legacy tools are on by default, disable composing)
read_only_agent = Agent(
    name="Gmail Reader Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(create_draft_email=False, send_email=False, send_email_reply=False)
    ],
    description="You are a Gmail reading specialist that can search, read and label emails.",
    instructions=[
        "You can search and read Gmail messages but cannot send or draft emails.",
        "Summarize email contents and extract key details and dates.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
)

# Example 2: Exclude dangerous functions (sending emails)
safe_gmail_agent = Agent(
    name="Safe Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(send_email=False, send_email_reply=False)],
    description="You are a Gmail agent with safe operations only.",
    instructions=[
        "You can read and draft emails but cannot send them.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
)

# Example 3: Full Gmail functionality (default -- all legacy tools enabled)
agent = Agent(
    name="Full Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools()],
    description="You are an expert Gmail Agent that can read, draft, send and label emails using Gmail.",
    instructions=[
        "While showing email contents, summarize the contents, extract key details and dates.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    # Read-only: find and summarize unread emails
    read_only_agent.print_response(
        "Search for the 5 most recent unread emails and summarize them",
        stream=True,
    )

    # Safe agent: draft without sending
    # safe_gmail_agent.print_response(
    #     "Draft a reply to the latest email from john@example.com",
    #     stream=True,
    # )

    # Full agent: find an email from a specific sender
    # agent.print_response(
    #     "Find the last email from john@example.com and show me the subject and summary",
    #     stream=True,
    # )
