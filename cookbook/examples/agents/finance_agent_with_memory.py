"""🗞️ Finance Agent with Memory - Your Market Analyst that remembers your preferences

1. Create virtual environment and install dependencies:
   - Run `uv venv --python 3.12` to create a virtual environment
   - Run `source .venv/bin/activate` to activate the virtual environment
   - Run `uv pip install agno openai sqlalchemy fastapi uvicorn yfinance duckduckgo-search` to install the dependencies
   - Run `ag setup` to connect your local env to Agno
   - Export your OpenAI key: `export OPENAI_API_KEY=<your_openai_key>`
2. Run the app:
   - Run `python cookbook/examples/agents/financial_agent_with_memory.py` to start the app
3. Chat with the agent:
   - Open `https://app.agno.com/playground?endpoint=localhost%3A7777`
   - Tell the agent your name and favorite stocks
   - Ask the agent to analyze your favorite stocks
"""

from textwrap import dedent

from agno.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

finance_agent_with_memory = Agent(
    name="Finance Agent with Memory",
    agent_id="financial_agent_with_memory",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[YFinanceTools(enable_all=True), DuckDuckGoTools()],
    memory=Memory(
        db=SqliteMemoryDb(table_name="agent_memory", db_file="tmp/agent_data.db"),
        model=OpenAIChat(id="gpt-4o-mini"),
        clear_memories=True,
        delete_memories=True,
    ),
    # Let the Agent create and manage user memories
    enable_agentic_memory=True,
    # Uncomment to always create memories from the input
    # can be used instead of enable_agentic_memory
    # enable_user_memories=True,
    storage=SqliteStorage(table_name="agent_sessions", db_file="tmp/agent_data.db"),
    # Add messages from the last 3 runs to the messages
    add_history_to_messages=True,
    num_history_runs=3,
    # Add the current datetime to the instructions
    add_datetime_to_instructions=True,
    # Use markdown formatting
    markdown=True,
    instructions=dedent("""\
        You are a Wall Street analyst. Your goal is to help users with financial analysis.

        Checklist for different types of financial analysis:
        1. Market Overview: Stock price, 52-week range.
        2. Financials: P/E, Market Cap, EPS.
        3. Insights: Analyst recommendations, rating changes.
        4. Market Context: Industry trends, competitive landscape, sentiment.

        Formatting guidelines:
        - Use tables for data presentation
        - Include clear section headers
        - Add emoji indicators for trends (📈 📉)
        - Highlight key insights with bullet points
    """),
)

app = Playground(agents=[finance_agent_with_memory]).get_app()

if __name__ == "__main__":
    serve_playground_app("financial_agent_with_memory:app", port=7777)
