from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.thinking import ThinkingTools
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ReasoningTools(
            think=True,
            analyze=True,
            add_instructions=True,
            add_few_shot=True,
        ),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions="Use tables where possible",
    markdown=True,
)
reasoning_agent.print_response(
    "Write a report comparing NVDA to TSLA",
    stream=True,
    show_full_reasoning=True,
    stream_intermediate_steps=True,
)

agent_storage: str = "tmp/agents.db"

thinking_web_agent = Agent(
    name="Thinking Web Agent",
    model=Claude(id="claude-3-7-sonnet-latest"),
    tools=[ThinkingTools(add_instructions=True), DuckDuckGoTools()],
    instructions=["Always include sources"],
    # Store the agent sessions in a sqlite database
    storage=SqliteDb(session_table="web_agent", db_file=agent_storage),
    # Adds the current date and time to the instructions
    add_datetime_to_context=True,
    # Adds the history of the conversation to the messages
    add_history_to_context=True,
    # Number of history responses to add to the messages
    num_history_responses=5,
    # Adds markdown formatting to the messages
    markdown=True,
)

thinking_finance_agent = Agent(
    name="Thinking Finance Agent",
    model=Claude(id="claude-3-7-sonnet-latest"),
    tools=[
        ThinkingTools(add_instructions=True),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions="Use tables to display data",
    storage=SqliteDb(session_table="finance_agent", db_file=agent_storage),
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_responses=5,
    markdown=True,
)

os = AgentOS(
    agents=[thinking_web_agent, thinking_finance_agent],
    name="Thinking OS",
    description="A playground for thinking",
    os_id="thinking-os",
)
app = os.get_app()

if __name__ == "__main__":
    os.serve(app="thinking_playground:app", reload=True)
