"""
DSPy ReAct agent with web search, served through AgentOS.

Uses DSPy's ReAct module with a live DuckDuckGo search tool.
Multi-turn conversations are persisted to Postgres and visible
in the AgentOS UI.

Requirements:
    pip install dspy ddgs

Usage:
    python cookbook/frameworks/dspy/dspy_session_agentos.py

Then call the API:
    # Streaming
    curl -X POST http://localhost:7777/agents/dspy-search/runs \\
        -F "message=What are the latest AI agent developments?" \\
        -F "stream=true" \\
        --no-buffer

    # Non-streaming
    curl -X POST http://localhost:7777/agents/dspy-search/runs \\
        -F "message=What is quantum computing?" \\
        -F "stream=false"

    # List agents
    curl http://localhost:7777/agents
"""

import dspy
from agno.agents.dspy import DSPyAgent
from agno.db.postgres import PostgresDb
from agno.os.app import AgentOS
from ddgs import DDGS


# ----- Define a live web search tool -----
def search_web(query: str) -> str:
    """Search the web for current information using DuckDuckGo."""
    results = DDGS().text(query, max_results=3)
    if not results:
        return f"No results found for: {query}"
    return "\n\n".join(f"- {r['title']}: {r['body']}" for r in results)


# ----- Configure DSPy (must be set on the main thread) -----
dspy.configure(lm=dspy.LM("openai/gpt-5.4"))

# ----- Create the DSPy ReAct agent with search + persistence -----
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

react_program = dspy.ReAct(
    signature="question -> answer",
    tools=[search_web],
    max_iters=5,
)

agent = DSPyAgent(
    name="DSPy Search Agent",
    description="A DSPy ReAct agent with live web search, served through AgentOS",
    program=react_program,
    db=db,
)

# ----- Serve through AgentOS -----
agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="dspy_session_agentos:app", reload=True)
