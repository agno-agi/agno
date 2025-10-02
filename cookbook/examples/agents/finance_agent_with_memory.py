"""🗞️ Finance Agent with Memory - Your Market Analyst that remembers your preferences

1. Create virtual environment and install dependencies:
   - Run `uv venv --python 3.12` to create a virtual environment
   - Run `source .venv/bin/activate` to activate the virtual environment
   - Run `uv pip install agno openai sqlalchemy fastapi uvicorn yfinance ddgs` to install the dependencies
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
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

finance_agent_with_memory = Agent(
    name="Finance Agent with Memory",
    id="financial_agent_with_memory",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[YFinanceTools(), DuckDuckGoTools()],
    # Let the Agent create and manage user memories
    enable_agentic_memory=True,
    # Uncomment to always create memories from the input
    # can be used instead of enable_agentic_memory
    # enable_user_memories=True,
    db=SqliteDb(
        session_table="agent_sessions",
        db_file="tmp/agent_data.db",
        memory_table="agent_memory",
    ),
    # Add messages from the last 3 runs to the messages
    add_history_to_context=True,
    num_history_runs=3,
    # Add the current datetime to the instructions
    add_datetime_to_context=True,
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

# Initialize the AgentOS with the workflows
agent_os = AgentOS(
    description="Example OS setup",
    agents=[finance_agent_with_memory],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="financial_agent_with_memory:app", reload=True)
