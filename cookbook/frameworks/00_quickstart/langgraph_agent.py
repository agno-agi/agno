"""
LangGraph Agent on AgentOS
==========================
A LangGraph chatbot, served through AgentOS.

Requirements:
    pip install langgraph langchain-openai

Usage:
    .venvs/demo/bin/python cookbook/frameworks/00_quickstart/langgraph_agent.py
"""

from agno.agents.langgraph import LangGraphAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph


def chatbot(state: MessagesState):
    return {"messages": [ChatOpenAI(model="gpt-5.4").invoke(state["messages"])]}


graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.set_entry_point("chatbot")
compiled = graph.compile()

agent = LangGraphAgent(
    name="LangGraph Chatbot",
    graph=compiled,
)

agent_os = AgentOS(
    agents=[agent],
    tracing=True,
    db=SqliteDb(db_file="tmp/agentos.db"),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="langgraph_agent:app", reload=True)
