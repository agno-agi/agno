"""Run `pip install openai exa_py duckduckgo-search yfinance pypdf sqlalchemy 'fastapi[standard]' youtube-transcript-api python-docx agno` to install dependencies."""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

agent_storage_file: str = "tmp/agents.db"
image_agent_storage_file: str = "tmp/image_agent.db"

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


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
    add_history_to_messages=True,
    num_history_responses=5,
    add_datetime_to_instructions=True,
    markdown=True,
)

cot_agent = Agent(
    name="COT Agent",
    role="Answer basic questions",
    agent_id="cot-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=SqliteStorage(
        table_name="cot_agent", db_file=agent_storage_file, auto_upgrade_schema=True
    ),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
    reasoning=True,
)

reasoning_model_agent = Agent(
    name="Reasoning Model Agent",
    role="Reasoning about Math",
    agent_id="reasoning-model-agent",
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=OpenAIChat(id="o3-mini"),
    instructions=["You are a reasoning agent that can reason about math."],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    storage=SqliteStorage(
        table_name="reasoning_model_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

reasoning_tool_agent = Agent(
    name="Reasoning Tool Agent",
    role="Answer basic questions",
    agent_id="reasoning-tool-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=SqliteStorage(
        table_name="reasoning_tool_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
    tools=[ReasoningTools()],
)

native_model_agent = Agent(
    model=OpenAIChat(id="o3-mini", reasoning_effort="high"),
    name="Native Model Agent",
    agent_id="native_model_agent",
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        )
    ],
    instructions="Use tables to display data.",
    show_tool_calls=True,
    markdown=True,
    storage=SqliteStorage(
        table_name="native_model_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

claude_thinking_agent = Agent(
    name="Claude Thinking Agent",
    agent_id="claude_thinking_agent",
    model=Claude(
        id="claude-3-7-sonnet-20250219",
        max_tokens=2048,
        thinking={"type": "enabled", "budget_tokens": 1024},
    ),
    markdown=True,
    storage=SqliteStorage(
        table_name="claude_thinking_agent",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

financial_news_team = Team(
    name="Financial News Team",
    team_id="financial_news_team",
    mode="route",
    members=[finance_agent, reasoning_tool_agent],
    instructions="You are a financial news team that is responsible for providing financial news to the user.",
    storage=SqliteStorage(
        table_name="financial_news_team",
        db_file=agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

app = Playground(
    agents=[
        cot_agent,
        reasoning_tool_agent,
        reasoning_model_agent,
        native_model_agent,
        claude_thinking_agent,
    ]
).get_app()

if __name__ == "__main__":
    serve_playground_app("reasoning_demo:app", reload=True)
