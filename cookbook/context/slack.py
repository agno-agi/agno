"""
Slack Context Provider
======================

Read-only Slack workspace access — search, channel history, threads,
user/channel lookups. Sending is intentionally disabled.

Run: pip install openai slack-sdk
Env: SLACK_BOT_TOKEN (or SLACK_TOKEN), OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.context.slack import SlackContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Build Provider
# ---------------------------------------------------------------------------
provider = SlackContextProvider()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=provider.get_tools(),
    instructions=[
        "You answer workplace questions by searching Slack.",
        provider.instructions(),
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Status:", provider.status())
    agent.print_response(
        "List the channels available in the workspace.",
        stream=True,
    )
