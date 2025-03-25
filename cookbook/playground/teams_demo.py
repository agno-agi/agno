from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.postgres import PostgresStorage
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.yfinance import YFinanceTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    agent_id="web_agent",
    instructions=[
        "You are an experienced web researcher and news analyst! 🔍",
    ],
    show_tool_calls=True,
    markdown=True,
    storage=PostgresStorage(
        table_name="web_agent", db_url=db_url, auto_upgrade_schema=True
    ),
)

finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    agent_id="finance_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions=[
        "You are a skilled financial analyst with expertise in market data! 📊",
        "Follow these steps when analyzing financial data:",
        "Start with the latest stock price, trading volume, and daily range",
        "Present detailed analyst recommendations and consensus target prices",
        "Include key metrics: P/E ratio, market cap, 52-week range",
        "Analyze trading patterns and volume trends",
    ],
    show_tool_calls=True,
    markdown=True,
)

simple_agent = Agent(
    name="Simple Agent",
    role="Simple agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=["You are a simple agent"],
)

research_agent = Agent(
    name="Research Agent",
    role="Research agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=["You are a research agent"],
    tools=[DuckDuckGoTools(), ExaTools()],
    agent_id="research_agent",
)

research_team = Team(
    name="Research Team",
    description="A team of agents that research the web",
    members=[research_agent, simple_agent],
    model=OpenAIChat(id="gpt-4o"),
    mode="coordinate",
    team_id="research_team",
    success_criteria=dedent("""\
        A comprehensive research report with clear sections and data-driven insights.
    """),
    instructions=[
        "You are the lead researcher of a research team! 🔍",
    ],
    add_datetime_to_instructions=True,
    show_tool_calls=True,
    markdown=True,
    enable_agentic_context=True,
)

agent_team = Team(
    name="Financial News Team",
    description="A team of agents that search the web for financial news and analyze it.",
    members=[web_agent, finance_agent, research_agent],
    model=OpenAIChat(id="gpt-4o"),
    mode="route",
    team_id="financial_news_team",
    success_criteria=dedent("""\
        A comprehensive financial news report with clear sections and data-driven insights.
    """),
    instructions=[
        "You are the lead editor of a prestigious financial news desk! 📰",
    ],
    add_datetime_to_instructions=True,
    show_tool_calls=True,
    markdown=True,
    enable_agentic_context=True,
    show_members_responses=True,
    debug_mode=True,
    storage=PostgresStorage(
        table_name="financial_news_team",
        db_url=db_url,
        mode="team",
        auto_upgrade_schema=True,
    ),
    expected_output="A good financial news report.",
    context="use USD as currency",
)

app = Playground(
    teams=[agent_team, research_team],
    agents=[web_agent, finance_agent, research_agent, simple_agent],
).get_app()

if __name__ == "__main__":
    serve_playground_app("teams_demo:app", reload=True)
