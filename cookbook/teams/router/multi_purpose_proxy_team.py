from textwrap import dedent

import requests
from agno.agent import Agent
from agno.media import Audio, Image
from agno.models.deepseek import DeepSeek
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.dalle import DalleTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.tools.calculator import CalculatorTools

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

writer_agent = Agent(
    name="Write Agent",
    role="Write content",
    model=OpenAIChat(id="gpt-4o"),
    description="You are an AI agent that can write content.",
    instructions=[
        "You are a versatile writer who can create content on any topic.",
        "When given a topic, write engaging and informative content in the requested format and style.",
        "If you receive mathematical expressions or calculations from the calculator agent, convert them into clear written text.",
        "Ensure your writing is clear, accurate and tailored to the specific request.",
        "Maintain a natural, engaging tone while being factually precise.",
    ],
)

audio_agent = Agent(
    name="Audio Agent",
    role="Analyze audio",
    model=Gemini(id="gemini-2.0-flash-exp"),
)

calculator_agent = Agent(
    name="Calculator Agent",
    model=OpenAIChat(id="gpt-4o"),
    role="Calculate",
    tools=[
        CalculatorTools(
            add=True,
            subtract=True,
            multiply=True,
            divide=True,
            exponentiate=True,
            factorial=True,
            is_prime=True,
            square_root=True,
        )
    ],
    show_tool_calls=True,
    markdown=True,
)

calculator_writer_team = Team(
    name="Calculator Writer Team",
    mode="coordinator",
    model=OpenAIChat("gpt-4.5-preview"),
    members=[calculator_agent, writer_agent],
    instructions=[
        "You are a team of two agents. The calculator agent and the writer agent.",
        "The calculator agent is responsible for calculating the result of the mathematical expression.",
        "The writer agent is responsible for writing the result of the mathematical expression in a clear and engaging manner."
        "You need to coordinate the work between the two agents and give the final response to the user.",
        "You need to give the final response to the user in the requested format and style.",
    ],
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
)

reasoning_agent = Agent(
    name="Reasoning Agent",
    role="Reasoning about Math",
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    instructions=["You are a reasoning agent that can reason about math."],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

agent_team = Team(
    name="Agent Team",
    mode="router",
    model=OpenAIChat("gpt-4.5-preview"),
    members=[web_agent, finance_agent, image_agent, audio_agent, calculator_writer_team, reasoning_agent],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
)

# Use web and finance agents to answer the question
# agent_team.print_response(
#     "Summarize analyst recommendations and share the latest news for NVDA", stream=True
# )
# agent_team.print_response(
#     "Calculate the sum of 10 and 20 and give write something about how you did the calculation", stream=True
# )

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

# Use the calculator writer team to calculate the result
# agent_team.print_response(
#     "What is the square root of 6421123 times the square root of 9485271", stream=True
# )

# Use the reasoning agent to reason about the result
agent_team.print_response(
    "9.11 and 9.9 -- which is bigger?", stream=True
)