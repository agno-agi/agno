"""
SendHQ Tools
============

An agent with its own email address: it reads what arrives, follows the
conversation, and answers inside the same thread with SendHQTools
(https://sendhq.cc).

Setup:
    1. Create an API key and verify a sending domain in the SendHQ dashboard
       (https://sendhq.cc/docs/quickstart).
    2. For the inbox example, add an inbox address on that domain
       (https://sendhq.cc/docs/inbound).

    export SENDHQ_API_KEY=re_...
    export SENDHQ_FROM_EMAIL="Support <support@your-domain.com>"
    export SENDHQ_TEST_RECIPIENT=you@example.com
    .venvs/demo/bin/python cookbook/91_tools/sendhq_tools.py
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.sendhq import SendHQTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Reads the inbox and answers each unread conversation in its own thread.
support_agent = Agent(
    name="Support Inbox Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[SendHQTools()],
    instructions=[
        "You answer the support inbox.",
        "List unread received email, read each conversation with get_thread, then answer with reply_to_email.",
        "Keep replies short and plain. Never invent order numbers, prices, or dates.",
    ],
    markdown=True,
)

# Only sends: useful for notifications where the agent must not read mail.
notifier_agent = Agent(
    name="Notifier Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[
        SendHQTools(
            enable_reply_to_email=False,
            enable_list_emails=False,
            enable_get_email=False,
            enable_get_thread=False,
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    recipient = getenv("SENDHQ_TEST_RECIPIENT")
    if recipient:
        notifier_agent.print_response(
            f"Email {recipient} a two-sentence summary of what SendHQTools lets an agent do. "
            "Use the subject 'Hello from an Agno agent'.",
            stream=True,
        )

    support_agent.print_response(
        "Check the inbox and answer every unread conversation.", stream=True
    )
