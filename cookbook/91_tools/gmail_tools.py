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

# Example 1: Include specific Gmail functions for reading only
read_only_agent = Agent(
    name="Gmail Reader Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            include_tools=[
                "get_unread_emails",
                "search_emails",
                "mark_email_as_read",
                "mark_email_as_unread",
                "list_custom_labels",
            ],
            add_instructions=False,
        )
    ],
    description="You are a Gmail reading specialist that can search, read and label emails.",
    instructions=[
        "You can search and read Gmail messages but cannot send or draft emails.",
        "You can mark emails as read or unread for processing workflows.",
        "You can list all available labels in the user's Gmail account.",
        "Summarize email contents and extract key details and dates.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
)

# Example 2: Exclude dangerous functions (sending emails)
safe_gmail_agent = Agent(
    name="Safe Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            exclude_tools=["send_email", "send_email_reply"], add_instructions=False
        )
    ],
    description="You are a Gmail agent with safe operations only.",
    instructions=[
        "You can read and draft emails but cannot send them.",
        "Show the email contents in a structured markdown format.",
    ],
    markdown=True,
)

# Example 3: Label Management Specialist Agent
label_manager_agent = Agent(
    name="Gmail Label Manager",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            include_tools=[
                "list_custom_labels",
                "apply_label",
                "remove_label",
                "delete_custom_label",
                "search_emails",
                "get_emails_by_context",
            ],
            add_instructions=False,
        )
    ],
    description="You are a Gmail label management specialist that helps organize emails with labels.",
    instructions=[
        "You specialize in Gmail label management operations.",
        "You can list existing custom labels, apply labels to emails, remove labels, and delete labels.",
        "Always be careful when deleting labels - confirm with the user first.",
        "When applying or removing labels, search for relevant emails first.",
        "Provide clear feedback on label operations performed.",
    ],
    markdown=True,
)

# Example 4: Full Gmail functionality (default)
agent = Agent(
    name="Full Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(add_instructions=False)],
    description="You are an expert Gmail Agent that can read, draft, send and label emails using Gmail.",
    instructions=[
        "Based on user query, you can read, draft, send and label emails using Gmail.",
        "While showing email contents, summarize the contents, extract key details and dates.",
        "Show the email contents in a structured markdown format.",
        "Attachments can be added to the email.",
        "When you need to modify an email, make sure to find its message_id and thread_id first.",
    ],
    markdown=True,
)

email = "<replace_with_email_address>"

if __name__ == "__main__":
    # Read-only: find and summarize an email
    read_only_agent.print_response(
        "Search for the 5 most recent unread emails and summarize them",
        stream=True,
    )

    # Label management: list labels
    # label_manager_agent.print_response(
    #     "List all my custom labels in Gmail.",
    #     stream=True,
    # )

    # Label management: apply labels
    # label_manager_agent.print_response(
    #     "Apply the 'Newsletters' label to emails from 'newsletter@company.com'. Process the last 5 emails.",
    #     stream=True,
    # )

    # Full agent: find an email from a specific sender
    # agent.print_response(
    #     f"Find the last email from {email} and show me the subject and summary",
    #     stream=True,
    # )

    # Full agent: send an email with attachment
    # agent.print_response(
    #     f"Send an email to {email} with subject 'Subject' "
    #     "and body 'Body' and attach the file 'tmp/attachment.pdf'",
    #     stream=True,
    # )
