"""
Multi-Framework AgentOS
=======================
Serve agents built with different frameworks — Agno, Claude Agent SDK,
LangGraph, and DSPy — through a single AgentOS instance. All agents
share the same runtime, API, UI, and session persistence.

Requirements:
    pip install claude-agent-sdk langgraph langchain-openai dspy

Usage:
    python cookbook/frameworks/multi_framework_agentos.py

Then open the AgentOS UI at http://localhost:7777 to see all four agents.
Or call them via API:

    # List all agents
    curl http://localhost:7777/agents

    # Agno native agent
    curl -X POST http://localhost:7777/agents/agno-assistant/runs \\
        -F "message=What is Agno?" -F "stream=true" --no-buffer

    # Claude Agent SDK
    curl -X POST http://localhost:7777/agents/claude-assistant/runs \\
        -F "message=Search for AI agent news" -F "stream=true" --no-buffer

    # LangGraph
    curl -X POST http://localhost:7777/agents/langgraph-assistant/runs \\
        -F "message=What is quantum computing?" -F "stream=true" --no-buffer

    # DSPy
    curl -X POST http://localhost:7777/agents/dspy-assistant/runs \\
        -F "message=Explain machine learning" -F "stream=true" --no-buffer
"""

import dspy
from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.agents.dspy import DSPyAgent
from agno.agents.langgraph import LangGraphAgent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph

# ---------------------------------------------------------------------------
# Shared database for session persistence
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# 1. Native Agno Agent
# ---------------------------------------------------------------------------
agno_agent = Agent(
    id="agno-assistant",
    name="Agno Assistant",
    description="A native Agno agent",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=["You are a helpful assistant. Be concise."],
    db=db,
)

# ---------------------------------------------------------------------------
# 2. Claude Agent SDK
# ---------------------------------------------------------------------------
claude_agent = ClaudeAgent(
    name="Claude Assistant",
    description="A Claude-powered assistant with web search",
    model="claude-sonnet-4-20250514",
    allowed_tools=["WebSearch"],
    permission_mode="acceptEdits",
    max_turns=5,
    db=db,
)

# ---------------------------------------------------------------------------
# 3. LangGraph Agent
# ---------------------------------------------------------------------------
llm = ChatOpenAI(model="gpt-5.4")


def chatbot(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.set_entry_point("chatbot")
compiled = graph.compile()

langgraph_agent = LangGraphAgent(
    name="LangGraph Assistant",
    description="A LangGraph chatbot",
    graph=compiled,
    db=db,
)

# ---------------------------------------------------------------------------
# 4. DSPy Agent
# ---------------------------------------------------------------------------
dspy.configure(lm=dspy.LM("openai/gpt-5.4"))

dspy_agent = DSPyAgent(
    name="DSPy Assistant",
    description="A DSPy chain-of-thought agent",
    program=dspy.ChainOfThought("question -> answer"),
    db=db,
)

# ---------------------------------------------------------------------------
# Serve all four through a single AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    name="Multi-Framework AgentOS",
    description="Four agents, four frameworks, one runtime",
    agents=[agno_agent, claude_agent, langgraph_agent, dspy_agent],
    db=db,
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="multi_framework_agentos:app", reload=True)
