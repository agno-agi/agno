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
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=["Always include sources"],
)

finance_agent = Agent(
    name="Finance Agent",
    role="Handle financial data requests",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions=["Use tables to display data"],
)

team_leader = Team(
    name="Reasoning Team Leader",
    mode="coordinate",
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[
        web_agent,
        finance_agent,
    ],
    tools=[ReasoningTools(add_instructions=True)],
    markdown=True,
    show_members_responses=True,
    enable_agentic_context=True,
    success_criteria="The team has successfully completed the task.",
)

team_leader.print_response(
    "Tell me 1 company in New York, 1 in San Francisco and 1 in Chicago and the stock price of each",
    stream=True,
    stream_intermediate_steps=True,
    show_full_reasoning=True,
)
