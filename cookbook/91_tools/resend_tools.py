"""
Resend Tools
=============================

Demonstrates resend tools.

``send_email`` sends an arbitrary recipient/subject/body using the host's Resend
API key. To avoid turning the agent into a data-exfiltration sink under prompt
injection, prefer the hardened configuration below: require human approval and
restrict recipients to an allowlist.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.resend import ResendTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

from_email = "<enter_from_email>"
to_email = "<enter_to_email>"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        ResendTools(
            from_email=from_email,
            # Gate every send behind human-in-the-loop approval.
            require_confirmation=True,
            # Only allow recipients in these domains (or use allowed_emails for
            # exact addresses).
            allowed_domains=["example.com"],
        )
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(f"Send an email to {to_email} greeting them with hello world")
