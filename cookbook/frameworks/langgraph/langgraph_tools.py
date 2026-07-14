"""
LangGraph agent with tool calls, wrapped in Agno's LangGraphAgent.

Requirements:
    pip install langgraph langchain-openai

Usage:
    .venvs/demo/bin/python libs/agno/agno/test.py
"""

import json

from agno.agents.langgraph import LangGraphAgent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


# ----- Define tools -----
@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    data = {
        "Paris": {"temp": "18C", "condition": "Sunny"},
        "London": {"temp": "12C", "condition": "Cloudy"},
        "Tokyo": {"temp": "22C", "condition": "Clear"},
    }
    return json.dumps(data.get(city, {"temp": "unknown", "condition": "unknown"}))


@tool
def get_population(city: str) -> str:
    """Get the population of a city."""
    data = {
        "Paris": "2.1 million",
        "London": "8.9 million",
        "Tokyo": "13.9 million",
    }
    return data.get(city, "unknown")


# ----- Build graph with tools -----
tools = [get_weather, get_population]
llm = ChatOpenAI(model="gpt-5.4").bind_tools(tools)


def chatbot(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


def should_continue(state: MessagesState):
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return "__end__"


graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.add_node("tools", ToolNode(tools))
graph.set_entry_point("chatbot")
graph.add_conditional_edges(
    "chatbot", should_continue, {"tools": "tools", "__end__": "__end__"}
)
graph.add_edge("tools", "chatbot")
compiled = graph.compile()


# ----- Wrap for Agno -----
agent = LangGraphAgent(
    name="LangGraph Tool Agent",
    graph=compiled,
)

# Streaming with tool calls visible
agent.print_response("What's the weather and population of Tokyo?", stream=True)
