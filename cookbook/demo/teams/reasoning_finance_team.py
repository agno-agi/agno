from agno.agent import Agent
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

# ************* Database Connection *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
# *******************************

# ************* Memory *************
memory = Memory(
    model=OpenAIChat(id="gpt-4.1"),
    db=PostgresMemoryDb(table_name="user_memories", db_url=db_url),
    delete_memories=True,
    clear_memories=True,
)
# *******************************

web_agent = Agent(
    name="Web Search Agent",
    role="Handle web search requests",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[DuckDuckGoTools()],
    storage=PostgresAgentStorage(
        db_url=db_url,
        table_name="web_agent_sessions",
    ),
    memory=memory,
    add_memory_references=True,
    instructions="Always include sources",
    add_datetime_to_instructions=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Handle financial data requests",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    storage=PostgresAgentStorage(
        db_url=db_url,
        table_name="finance_agent_sessions",
    ),
    memory=memory,
    instructions=[
        "You are a financial data specialist. Provide concise and accurate data.",
        "Use tables to display stock prices, fundamentals (P/E, Market Cap), and recommendations.",
        "Clearly state the company name and ticker symbol.",
        "Briefly summarize recent company-specific news if available.",
        "Focus on delivering the requested financial data points clearly.",
    ],
    add_memory_references=True,
    add_datetime_to_instructions=True,
)


def get_reasoning_finance_team():
    return Team(
        name="Reasoning Finance Team",
        mode="coordinate",
        model=Claude(id="claude-3-7-sonnet-latest"),
        members=[
            web_agent,
            finance_agent,
        ],
        tools=[ReasoningTools(add_instructions=True)],
        instructions=[
            "Use tables to display data",
            "Only output the final answer, no other text.",
        ],
        storage=PostgresAgentStorage(
            db_url=db_url,
            table_name="reasoning_finance_team_sessions",
        ),
        memory=memory,
        markdown=True,
        enable_agentic_memory=True,
        show_members_responses=True,
        enable_agentic_context=True,
        add_datetime_to_instructions=True,
        success_criteria="The team has successfully completed the task.",
    )
