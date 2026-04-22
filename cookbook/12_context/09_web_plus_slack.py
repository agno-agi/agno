"""
Team briefing: Slack + Web
==========================

Cross-reference internal Slack discussion with external industry
news to produce a short briefing.

Workflow the agent performs:
  1. Pull recent messages from an engineering Slack channel
     (``query_slack`` → ``get_channel_history``).
  2. For each topic it surfaces, find a current external reference
     (``query_web`` → Exa search).
  3. Return a briefing tying each internal thread to a supporting
     external source.

The compositional shape — one provider's output informing the next
provider's query — is the payoff of multi-provider. Parallel
"two unrelated questions" is a weaker demo; real workflows chain.

Requires:
    OPENAI_API_KEY
    EXA_API_KEY        (https://dashboard.exa.ai/)
    SLACK_BOT_TOKEN    (or SLACK_TOKEN fallback; scopes: channels:read,
                        channels:history, users:read)
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.slack import SlackContextProvider
from agno.context.web import ExaBackend, WebContextProvider
from agno.models.openai import OpenAIResponses

# Sub-agents do the tool work — cheaper model. Outer agent synthesizes.
provider_model = OpenAIResponses(id="gpt-5.4-mini")

web = WebContextProvider(backend=ExaBackend(), model=provider_model)
slack = SlackContextProvider(model=provider_model)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[*web.get_tools(), *slack.get_tools()],
    instructions="\n".join([web.instructions(), slack.instructions()]),
    markdown=True,
)


if __name__ == "__main__":
    print(f"web.status()   = {web.status()}")
    print(f"slack.status() = {slack.status()}\n")

    prompt = (
        "I'm prepping a short briefing for our weekly engineering sync. "
        "Do this:\n"
        "  1. Pull the 10 most recent messages from the #agents Slack "
        "channel and identify 2 distinct topics under discussion.\n"
        "  2. For each topic, find one current (last ~month) article, "
        "release, or reference online that would be useful to link.\n"
        "\n"
        "Format as a short markdown briefing:\n"
        "  - **Topic** — 1-sentence Slack context → [external reference](url)\n"
        "\n"
        "If a topic has no clear external reference, say so; don't invent URLs."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
