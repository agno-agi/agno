from textwrap import dedent

import requests

from agno.agent import Agent
from agno.media import Audio, Image
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.dalle import DalleTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=["Always include sources"],
)


finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions=["Use tables to display data"],
)

image_agent = Agent(
    name="Image Agent",
    role="Analyze or generate images",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools()],
    description="You are an AI agent that can analyze images or create images using DALL-E.",
    instructions=[
        "When the user asks you about an image, give your best effort to analyze the image and return a description of the image.",
        "When the user asks you to create an image, use the DALL-E tool to create an image.",
        "The DALL-E tool will return an image URL.",
        "Return the image URL in your response in the following format: `![image description](image URL)`",
    ],
)


audio_agent = Agent(
    name="Audio Agent",
    role="Analyze audio",
    model=Gemini(id="gemini-2.0-flash-exp"),
)

agent_team = Team(
    name="Agent Team",
    mode="router",
    model=OpenAIChat("gpt-4.5-preview"),
    members=[web_agent, finance_agent, image_agent, audio_agent],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
)

# Use web and finance agents to answer the question
agent_team.print_response(
    "Summarize analyst recommendations and share the latest news for NVDA", stream=True
)

# image_path = Path(__file__).parent.joinpath("sample.jpg")
# # Use image agent to analyze the image
# agent_team.print_response(
#     "Write a 3 sentence fiction story about the image",
#     images=[Image(filepath=image_path)],
# )

# # Use audio agent to analyze the audio
# url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"
# response = requests.get(url)
# audio_content = response.content
# # Give a sentiment analysis of this audio conversation. Use speaker A, speaker B to identify speakers.
# agent_team.print_response(
#     "Give a sentiment analysis of this audio conversation. Use speaker A, speaker B to identify speakers.",
#     audio=[Audio(content=audio_content)],
# )

# # Use image agent to generate an image
# agent_team.print_response(
#     "Generate an image of a cat", stream=True
# )
