from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=["Always include sources"],
    expected_output=dedent("""\
    ## {title}

    {Answer to the user's question}
    """),
    # This will make the agent respond directly to the user, rather than through the team leader.
    respond_directly=True,
    markdown=True,
)


finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions=["Use tables to display data"],
    expected_output=dedent("""\
    ## {title}

    {Answer to the user's question}
    """),
    # This will make the agent respond directly to the user, rather than through the team leader.
    respond_directly=True,
    markdown=True,
)

agent_team = Agent(
    team=[web_agent, finance_agent],
    instructions=["Always include sources", "Use tables to display data"],
    markdown=True,
    debug_mode=True,
)

agent_team.print_response(
    "Summarize analyst recommendations and share the latest news for NVDA", stream=True
)
