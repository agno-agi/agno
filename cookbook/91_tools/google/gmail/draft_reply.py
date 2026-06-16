"""
Gmail Draft Reply Agent
=======================
Reads a conversation thread and drafts a contextual reply.
The agent never sends -- it only creates drafts for human review.

Key concepts:
- Thread-aware drafting: thread_id + message_id link the draft to the conversation

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Gmail API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Draft Reply Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools()],
    instructions=[
        "Match the tone and formality of the existing conversation.",
        "Keep replies concise and professional unless instructed otherwise.",
        "Always create a draft -- never send directly.",
        "Summarize the thread context so the user knows what the reply addresses.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

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
