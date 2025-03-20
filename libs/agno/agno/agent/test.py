# from typing import List

# from pydantic import BaseModel, Field
# from rich.pretty import pprint  # noqa

# from agno.agent import Agent, RunResponse  # noqa
# from agno.models.openai import OpenAIChat


# class MovieScript(BaseModel):
#     setting: str = Field(..., description="Provide a nice setting for a blockbuster movie.")
#     ending: str = Field(
#         ...,
#         description="Ending of the movie. If not available, provide a happy ending.",
#     )
#     genre: str = Field(
#         ...,
#         description="Genre of the movie. If not available, select action, thriller or romantic comedy.",
#     )
#     name: str = Field(..., description="Give a name to this movie")
#     characters: List[str] = Field(..., description="Name of characters for this movie.")
#     storyline: str = Field(..., description="3 sentence storyline for the movie. Make it exciting!")


# # Agent that uses JSON mode
# json_mode_agent = Agent(
#     model=OpenAIChat(id="gpt-4o"),
#     description="You write movie scripts.",
#     response_model=MovieScript,
#     show_tool_calls=True,
# )

# # Agent that uses structured outputs
# structured_output_agent = Agent(
#     model=OpenAIChat(id="gpt-4o-2024-08-06"),
#     description="You write movie scripts.",
#     response_model=MovieScript,
#     structured_outputs=True,
#     show_tool_calls=True,
# )


# Get the response in a variable
# json_mode_response: RunResponse = json_mode_agent.run("New York")
# pprint(json_mode_response.content)
# structured_output_response: RunResponse = structured_output_agent.run("New York")
# pprint(structured_output_response.content)

# json_mode_agent.print_response("New York")
# structured_output_agent.print_response("New York")

from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from agno.tools.wikipedia import WikipediaTools
import asyncio

agent = Agent(
    model=OpenAIChat(id="gpt-4o"), markdown=True, tools=[YFinanceTools(), WikipediaTools()], show_tool_calls=True
)

# Get the response in a variable
# run: RunResponse = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
# agent.print_response("What is current prince of stock TSLA? Also give brief history of company tesla", stream=True)
asyncio.run(agent.aprint_response(
    "What is current prince of stock TSLA? Also give brief history of company tesla", stream=True))

agent.run_response.metrics

# from typing import List, Optional

# from pydantic import BaseModel, Field
# from rich.pretty import pprint  # noqa

# from agno.agent import Agent, RunResponse  # noqa
# from agno.models.openai import OpenAIChat
# from agno.tools.wikipedia import WikipediaTools
# from agno.tools.yfinance import YFinanceTools


# class CompanyStockInfo(BaseModel):
#     """Information about a company."""

#     company_name: str = Field(..., description="The full name of the company")
#     company_history: str = Field(..., description="Brief history of the company (3-5 sentences)")
#     founded_year: Optional[int] = Field(None, description="The year the company was founded")
#     # ceo: Optional[str] = Field(None, description="Current CEO of the company")


# # Create an agent that combines stock data with company information
# stock_info_agent = Agent(
#     model=OpenAIChat(id="gpt-4o"),
#     description="You are a web crawler that gets info about various companies like history, founded year, etc.",
#     instructions=[
#         "Use Wikipedia to research the company's history and key information.",
#         "Format the response according to the CompanyStockInfo schema.",
#         "Make sure all numerical data is accurate and up-to-date.",
#         "If a field is truly unknown, leave it as null.",
#     ],
#     # Use both YFinance and Wikipedia tools
#     tools=[WikipediaTools()],
#     show_tool_calls=True,
#     response_model=CompanyStockInfo,
#     structured_outputs=True,
# )

# # Print the response in the terminal
# stock_info_agent.print_response("Give me information about Tesla Company")

# # # Try with just a ticker symbol
# # stock_info_agent.print_response("What's the latest on NVDA?")

# # # Try with another company
# # stock_info_agent.print_response("Analyze Microsoft stock")
