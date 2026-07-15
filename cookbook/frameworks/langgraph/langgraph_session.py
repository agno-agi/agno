"""
LangGraph agent with session persistence.

Demonstrates multi-turn conversations where chat history is persisted
to Agno's DB. Each run is stored as a session with messages, so you
can resume conversations and see history in the AgentOS UI.

Requirements:
    pip install langchain-openai langgraph

Usage:
    python cookbook/frameworks/langgraph/langgraph_session.py
"""

from agno.agents.langgraph import LangGraphAgent
from agno.db.postgres import PostgresDb
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph

# ----- Build a simple LangGraph chatbot -----
llm = ChatOpenAI(model="gpt-5.4")


def chatbot(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.set_entry_point("chatbot")
compiled = graph.compile()

# ----- Create agent with SQLite persistence -----
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = LangGraphAgent(
    name="LangGraph Chat",
    graph=compiled,
    db=db,
)

SESSION_ID = "demo-session-1"

# Turn 1
agent.print_response(
    "What is quantum computing?",
    stream=True,
    session_id=SESSION_ID,
)

# Turn 2 — same session
agent.print_response(
    "How does it compare to classical computing?",
    stream=True,
    session_id=SESSION_ID,
)

# Turn 3
agent.print_response(
    "Summarize what we discussed",
    stream=True,
    session_id=SESSION_ID,
)

print("\n--- Session persisted to tmp/langgraph_sessions.db ---")
print(f"Session ID: {SESSION_ID}")
