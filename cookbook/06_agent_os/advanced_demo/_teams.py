from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

web_agent = Agent(
    name="Web Search Agent",
    role="Handle web search requests",
    model=Claude(id="claude-3-7-sonnet-latest"),
    db=PostgresDb(db_url=db_url, session_table="web_agent_sessions"),
    tools=[DuckDuckGoTools()],
    instructions=["Always include sources"],
)

finance_agent = Agent(
    name="Finance Agent",
    role="Handle financial data requests",
    model=Claude(id="claude-3-7-sonnet-latest"),
    db=PostgresDb(db_url=db_url, session_table="finance_agent_sessions"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions=["Use tables to display data"],
)

finance_reasoning_team = Team(
    name="Reasoning Team Leader",
    model=Claude(id="claude-3-7-sonnet-latest"),
    db=PostgresDb(db_url=db_url, session_table="finance_reasoning_team_sessions"),
    members=[
        web_agent,
        finance_agent,
    ],
    tools=[ReasoningTools(add_instructions=True)],
    markdown=True,
    show_members_responses=True,
)
