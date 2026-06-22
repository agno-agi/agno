"""
Standalone usage of a LangGraph agent with Agno's .run() and .print_response() methods.

Requirements:
    pip install langgraph langchain-openai

Usage:
    .venvs/demo/bin/python cookbook/frameworks/langgraph_basic.py
"""

from agno.agents.langgraph import LangGraphAgent
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph


# ----- Build a LangGraph agent -----
def chatbot(state: MessagesState):
    return {"messages": [ChatOpenAI(model="gpt-5.4").invoke(state["messages"])]}


graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.set_entry_point("chatbot")
compiled = graph.compile()


# ----- Wrap it for Agno -----
agent = LangGraphAgent(
    name="LangGraph Chatbot",
    graph=compiled,
)

# Use .print_response() just like a native Agno agent
agent.print_response("What is quantum computing?", stream=True)
