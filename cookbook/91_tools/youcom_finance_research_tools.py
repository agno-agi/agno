"""You.com Finance Research API — Cookbook Example

Demonstrates using ``YouFinanceResearchTools`` to answer a financial
research question through an Agno Agent.

Requirements:
    pip install agno openai python-dotenv

Environment variables:
    YDC_API_KEY       – You.com API key  (https://you.com/platform/api-keys)
    Azure_API_KEY     – Azure OpenAI API key
    Azure_Endpoint    – Azure OpenAI endpoint
"""

import os

from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from agno.tools.youcom.finance import YouFinanceResearchTools
from dotenv import load_dotenv

load_dotenv()

agent = Agent(
    id="You_Finance_Research_Agent",
    model=OpenAILike(
        id="gpt-5.4-mini",
        api_key=os.getenv("Azure_API_KEY"),
        base_url=os.getenv("Azure_Endpoint"),
        request_params={"parallel_tool_calls": False},
    ),
    tools=[
        YouFinanceResearchTools(
            format="markdown",
            show_results=True,
            research_effort="deep",
            timeout=150,  # Timeout should be set properly because finance research APIs take time
        ),
    ],
    tool_call_limit=1,
    debug_mode=True,
    debug_level=2,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Compare the free cash flow generation of Apple, Microsoft, and Alphabet "
        "over the past three fiscal years.",
        markdown=True,
    )
