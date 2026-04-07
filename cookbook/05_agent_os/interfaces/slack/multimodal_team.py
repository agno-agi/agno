"""
Multimodal Team
===============

Tests streaming a multi-agent team with multimodal input/output in Slack.

Capabilities tested:
  - Image INPUT:  Send an image to the bot, team analyzes it (GPT-4o vision)
  - Image OUTPUT: Ask to generate an image, DALL-E creates it, uploaded to Slack
  - File INPUT:   Send a CSV/text file, team analyzes it
  - Combined:     Send image + ask to modify/recreate it

Team members:
  - Vision Analyst: Understands images and files via GPT-4o
  - Creative Agent: Generates images via DALL-E + web search

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history,
             files:read, files:write
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools.dalle import DalleTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Team Members
# ---------------------------------------------------------------------------

vision_analyst = Agent(
    name="Vision Analyst",
    model=OpenAIChat(id="gpt-4o"),
    role="Analyzes images, files, and visual content in detail.",
    instructions=[
        "You are an expert visual analyst.",
        "When given an image, describe it thoroughly: subjects, colors, composition, text, mood.",
        "When given files (CSV, code, text), analyze their content and provide insights.",
        "Always format with markdown: bold, italics, bullet points.",
    ],
    markdown=True,
)

creative_agent = Agent(
    name="Creative Agent",
    model=OpenAIChat(id="gpt-4o"),
    role="Generates images with DALL-E and searches the web.",
    tools=[DalleTools(), WebSearchTools()],
    instructions=[
        "You are a creative assistant with image generation abilities.",
        "Use DALL-E to generate images when asked.",
        "Use web search when you need reference information.",
        "Describe generated images briefly after creation.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

multimodal_team = Team(
    name="Multimodal Team",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o"),
    members=[vision_analyst, creative_agent],
    instructions=[
        "Route image analysis and file analysis tasks to Vision Analyst.",
        "Route image generation and web search tasks to Creative Agent.",
        "If the user sends an image and asks to recreate/modify it, first ask Vision Analyst to describe it, then ask Creative Agent to generate a new version.",
    ],
    show_members_responses=False,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    teams=[multimodal_team],
    interfaces=[
        Slack(
            team=multimodal_team,
            streaming=True,
            reply_to_mentions_only=True,
            suggested_prompts=[
                {
                    "title": "Analyze",
                    "message": "Send me an image and I'll analyze it in detail",
                },
                {
                    "title": "Generate",
                    "message": "Generate an image of a sunset over mountains",
                },
                {"title": "Search", "message": "Search for the latest AI art trends"},
            ],
        )
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="multimodal_team:app", reload=True)
