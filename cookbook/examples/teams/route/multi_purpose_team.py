from pathlib import Path

from agno.agent import Agent
from agno.media import Audio, File, Image  # type: ignore
from agno.models.anthropic import Claude
from agno.models.deepseek import DeepSeek
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.dalle import DalleTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.e2b import E2BTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools
from agno.utils.media import download_file

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

file_analysis_agent = Agent(
    name="File Analysis Agent",
    role="Analyze files",
    model=Claude(id="claude-3-7-sonnet-latest"),
    description="You are an AI agent that can analyze files.",
    instructions=[
        "You are an AI agent that can analyze files.",
        "You are given a file and you need to answer questions about the file.",
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
    mode="coordinate",
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

code_execution_agent = Agent(
    name="Code Execution Sandbox",
    agent_id="e2b-sandbox",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[E2BTools()],
    markdown=True,
    show_tool_calls=True,
    instructions=[
        "You are an expert at writing and validating Python code using a secure E2B sandbox environment.",
        "Your primary purpose is to:",
        "1. Write clear, efficient Python code based on user requests",
        "2. Execute and verify the code in the E2B sandbox",
        "3. Share the complete code with the user, as this is the main use case",
        "4. Provide thorough explanations of how the code works",
        "",
    ],
)

agent_team = Team(
    name="Agent Team",
    mode="route",
    model=Claude(id="claude-3-5-sonnet-latest"),
    members=[
        web_agent,
        finance_agent,
        image_agent,
        audio_agent,
        calculator_writer_team,
        reasoning_agent,
        file_analysis_agent,
        code_execution_agent,
    ],
    instructions=[
        "You are a team of agents that can answer questions about the web, finance, images, audio, and files.",
        "You can use your member agents to answer the questions.",
        "if you are asked about a file, use the file analysis agent to analyze the file.",
        "You can also answer directly, you don't HAVE to forward the question to a member agent.",
    ],
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
)

# Use the reasoning agent to reason about the result
agent_team.print_response(
    "What is the square root of 6421123 times the square root of 9485271", stream=True
)
agent_team.print_response(
    "Calculate the sum of 10 and 20 and give write something about how you did the calculation",
    stream=True,
)

# Use web and finance agents to answer the question
agent_team.print_response(
    "Summarize analyst recommendations and share the latest news for NVDA", stream=True
)

# image_path = Path(__file__).parent.joinpath("sample.jpg")
# # # Use image agent to analyze the image
# agent_team.print_response(
#     "Write a 3 sentence fiction story about the image",
#     images=[Image(filepath=image_path)],
# )

# Use audio agent to analyze the audio
# url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"
# response = requests.get(url)
# audio_content = response.content
# # Give a sentiment analysis of this audio conversation. Use speaker A, speaker B to identify speakers.
# agent_team.print_response(
#     "Give a sentiment analysis of this audio conversation. Use speaker A, speaker B to identify speakers.",
#     audio=[Audio(content=audio_content)],
# )

# Use image agent to generate an image
# agent_team.print_response(
#     "Generate an image of a cat", stream=True
# )

# Use the calculator writer team to calculate the result
# agent_team.print_response(
#     "What is the square root of 6421123 times the square root of 9485271", stream=True
# )

# Use the code execution agent to write and execute code
# agent_team.print_response(
#     "write a python code to calculate the square root of 6421123 times the square root of 9485271",
#     stream=True,
# )


# # Use the reasoning agent to reason about the result
# agent_team.print_response("9.11 and 9.9 -- which is bigger?", stream=True)


# pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")

# # Download the file using the download_file function
# download_file(
#     "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf", str(pdf_path)
# )
# # Use file analysis agent to analyze the file
# agent_team.print_response(
#     "Summarize the contents of the attached file.",
#     files=[
#         File(
#             filepath=pdf_path,
#         ),
#     ],
# )
