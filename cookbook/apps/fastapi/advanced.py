
from agno.agent import Agent
from agno.app.fastapi.app import FastAPIApp
from agno.memory.v2 import Memory
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

agent_storage_file: str = "tmp/agents.db"
memory_storage_file: str = "tmp/memory.db"

memory_db = SqliteMemoryDb(table_name="memory", db_file=memory_storage_file)

# No need to set the model, it gets set by the agent to the agent's model
memory = Memory(db=memory_db)

simple_agent = Agent(
    name="Simple Agent",
    role="Answer basic questions",
    agent_id="simple-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=SqliteStorage(
        table_name="simple_agent", db_file=agent_storage_file, auto_upgrade_schema=True
    ),
    memory=memory,
    enable_user_memories=True,
    add_history_to_messages=True,
    num_history_responses=5,
    add_datetime_to_instructions=True,
    markdown=True,
)

web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    agent_id="web-agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "Break down the users request into 2-3 different searches.",
        "Always include sources",
    ],
    storage=SqliteStorage(
        table_name="web_agent", db_file=agent_storage_file, auto_upgrade_schema=True
    ),
    memory=memory,
    enable_user_memories=True,
    add_history_to_messages=True,
    num_history_responses=5,
    add_datetime_to_instructions=True,
    markdown=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    agent_id="finance-agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        )
    ],
    instructions=["Always use tables to display data"],
    storage=SqliteStorage(
        table_name="finance_agent", db_file=agent_storage_file, auto_upgrade_schema=True
    ),
    memory=memory,
    enable_user_memories=True,
    add_history_to_messages=True,
    num_history_responses=5,
    add_datetime_to_instructions=True,
    markdown=True,
)


fastapi_app = FastAPIApp(
    agents=[
        simple_agent,
        web_agent,
        finance_agent,
    ],
    app_id="advanced-app",
    name="Advanced FastAPI App",
    description="A FastAPI app for advanced agents",
)
app = fastapi_app.get_app()

if __name__ == "__main__":
    fastapi_app.serve(app="advanced:app", port=8001, reload=True)
