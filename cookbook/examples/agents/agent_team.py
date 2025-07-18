from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

web_agent = Agent(
    name="Web Search Agent",
    role="Handle web search requests",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions="Always include sources.",
    add_datetime_to_instructions=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Handle financial data requests",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions="Use tables to display data.",
    add_datetime_to_instructions=True,
)

team_leader = Team(
    name="Reasoning Finance Team Leader",
    mode="coordinate",
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[web_agent, finance_agent],
    tools=[ReasoningTools(add_instructions=True)],
    instructions=[
        "Use tables to display data.",
        "Only respond with the final answer, no other text.",
    ],
    markdown=True,
    show_members_responses=True,
    enable_agentic_context=True,
    add_datetime_to_instructions=True,
    success_criteria="The team has successfully completed the task.",
)

task = """\
Analyze the semiconductor market performance focusing on:
- NVIDIA (NVDA)
- AMD (AMD)
- Intel (INTC)
- Taiwan Semiconductor (TSM)
Compare their market positions, growth metrics, and future outlook."""

team_leader.print_response(
    task,
    stream=True,
    stream_intermediate_steps=True,
    show_full_reasoning=True,
)
