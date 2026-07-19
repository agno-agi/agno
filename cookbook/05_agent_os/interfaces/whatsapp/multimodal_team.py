"""
Multimodal Team
===============

A coordinated team with a Vision Analyst and a Creative Agent that
handles image analysis, image generation, and web research over WhatsApp.

Send a photo to get it analyzed, or ask for an image to be generated.
For redesign requests, the team analyzes first then creates.

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.team import Team
from agno.tools.dalle import DalleTools
from agno.tools.websearch import WebSearchTools

vision_analyst = Agent(
    name="Vision Analyst",
    model=OpenAIChat(id="gpt-4o"),
    role="Analyzes images, files, and visual content in detail.",
    instructions=[
        "You are an expert visual analyst.",
        "When given an image, describe it thoroughly: subjects, colors, composition, text, mood.",
        "When given files (CSV, code, text), analyze their content and provide insights.",
        "Keep analysis concise but detailed.",
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

multimodal_team = Team(
    name="Multimodal Team",
    mode="coordinate",
    model=OpenAIChat(id="gpt-4o"),
    members=[vision_analyst, creative_agent],
    instructions=[
        "Route image analysis and file analysis tasks to Vision Analyst.",
        "Route image generation and web search tasks to Creative Agent.",
        "If the user sends an image and asks to recreate or modify it, "
        "first ask Vision Analyst to describe it, then ask Creative Agent "
        "to generate a new version based on that description.",
    ],
    show_members_responses=False,
    markdown=True,
)

agent_os = AgentOS(
    teams=[multimodal_team],
    interfaces=[Whatsapp(team=multimodal_team)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="multimodal_team:app", reload=True)
