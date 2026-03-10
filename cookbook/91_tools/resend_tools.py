"""
Resend Tools
=============================

Demonstrates resend tools.
"""

from agno.agent import Agent
from agno.tools.resend import ResendTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


from_email = "<enter_from_email>"
to_email = "<enter_to_email>"

agent = Agent(tools=[ResendTools(from_email=from_email)])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(f"Send an email to {to_email} greeting them with hello world")
