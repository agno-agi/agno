"""
Gmail Draft Reply Agent
=======================
Reads a conversation thread and drafts a contextual reply.

The agent chains: search_threads (find the conversation) -> get_thread
(load full context) -> draft_email (create a reply draft with thread_id
so it appears threaded in Gmail).

The agent never sends -- it only creates drafts for human review.

Setup: See gmail_tools.py for Google OAuth credential setup.
Run: pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools

agent = Agent(
    name="Draft Reply Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(search_threads=True, get_thread=True, draft_email=True)],
    instructions=[
        "Match the tone and formality of the existing conversation.",
        "Keep replies concise and professional unless instructed otherwise.",
        "Always create a draft -- never send directly.",
        "Summarize the thread context so the user knows what the reply addresses.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Find the most recent thread about 'project update' and draft a reply "
        "acknowledging the update and asking about next steps",
        stream=True,
    )

    # Draft a reply to a specific sender
    # agent.print_response(
    #     "Find the latest email from john@example.com and draft a polite follow-up reply",
    #     stream=True,
    # )
