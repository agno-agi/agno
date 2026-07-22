"""
Agent-to-Agent Communication: AI Coworkers
===========================================
Two AI coworkers that can @mention each other in Slack.

- Slack Agent: Project coordinator with SlackTools
- Dash: Research specialist

When Slack Agent @mentions Dash, Dash receives the agent message
(thanks to respond_to_other_apps=True) and responds.

Setup:
  1. Two Slack apps installed to the same workspace
  2. Event Subscription URLs (separate ngrok domains, same port 7777):
       Slack Agent -> https://slack-agent.ngrok.app/slack/agent/events
       Dash        -> https://slack-dash.ngrok.app/slack/dash/events
  3. Environment variables:
       SLACK_AGENT_BOT_TOKEN, SLACK_AGENT_SIGNING_SECRET
       SLACK_DASH_BOT_TOKEN, SLACK_DASH_SIGNING_SECRET
  4. ngrok: ngrok start slack-agent slack-dash

Key flag: respond_to_other_apps=True
  - Default (False): Messages from other Slack apps/bots are dropped
  - True: Peer app messages are processed (own messages still dropped)

Loop safety:
  - Slack Agent keeps respond_to_other_apps=False (only hears humans)
  - Dash sets respond_to_other_apps=True (hears Slack Agent)
  - This asymmetry prevents infinite ping-pong loops
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.slack import SlackTools

# ---------------------------------------------------------------------------
# Slack Agent: Project Coordinator
# ---------------------------------------------------------------------------

slack_agent = Agent(
    name="Slack Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[SlackTools(token=getenv("SLACK_AGENT_BOT_TOKEN"))],
    instructions=[
        "You are a project coordinator. You help with general questions.",
        "For research-heavy tasks, delegate to your coworker Dash by "
        "@mentioning them in your response.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Dash: Research Specialist
# ---------------------------------------------------------------------------

dash = Agent(
    name="Dash",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You are Dash, a research specialist.",
        "When a coworker asks you something, provide a helpful response.",
        "Be helpful and professional.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[slack_agent, dash],
    interfaces=[
        Slack(
            agent=slack_agent,
            prefix="/slack/agent",
            token=getenv("SLACK_AGENT_BOT_TOKEN"),
            signing_secret=getenv("SLACK_AGENT_SIGNING_SECRET"),
            reply_to_mentions_only=True,
        ),
        Slack(
            agent=dash,
            prefix="/slack/dash",
            token=getenv("SLACK_DASH_BOT_TOKEN"),
            signing_secret=getenv("SLACK_DASH_SIGNING_SECRET"),
            reply_to_mentions_only=True,
            respond_to_other_apps=True,  # Dash can hear Slack Agent's @mentions
        ),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="respond_to_other_apps:app")
