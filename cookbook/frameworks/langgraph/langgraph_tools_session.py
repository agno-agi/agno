"""
LangGraph agent with tools and session persistence.

Demonstrates multi-turn conversations with tool calls, where the full
conversation history (including tool results) is persisted to Agno's DB.

Requirements:
    pip install langchain-openai langgraph

Usage:
    python cookbook/frameworks/langgraph/langgraph_tools_session.py
"""

from agno.agents.langgraph import LangGraphAgent
from agno.db.postgres import PostgresDb
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


# ----- Define tools -----
@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    weather_data = {
        "new york": "72F, partly cloudy",
        "london": "58F, rainy",
        "tokyo": "80F, sunny",
        "paris": "65F, overcast",
        "san francisco": "60F, foggy",
    }
    return weather_data.get(city.lower(), f"Weather data not available for {city}")


@tool
def get_population(city: str) -> str:
    """Get the population of a city."""
    pop_data = {
        "new york": "8.3 million",
        "london": "8.9 million",
        "tokyo": "13.9 million",
        "paris": "2.1 million",
        "san francisco": "870,000",
    }
    return pop_data.get(city.lower(), f"Population data not available for {city}")


# ----- Build the LangGraph with tools -----
tools = [get_weather, get_population]
llm = ChatOpenAI(model="gpt-5.4").bind_tools(tools)


def chatbot(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


def should_continue(state: MessagesState):
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return "end"


graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.add_node("tools", ToolNode(tools))
graph.set_entry_point("chatbot")
graph.add_conditional_edges(
    "chatbot", should_continue, {"tools": "tools", "end": "__end__"}
)
graph.add_edge("tools", "chatbot")
compiled = graph.compile()

# ----- Create agent with Postgres persistence -----
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = LangGraphAgent(
    name="LangGraph Tools Agent",
    graph=compiled,
    db=db,
)

SESSION_ID = "tools-session-1"

# Turn 1 — triggers tool calls
agent.print_response(
    "What's the weather in Tokyo?",
    stream=True,
    session_id=SESSION_ID,
)

# Turn 2 — follow-up in same session, triggers different tool
agent.print_response(
    "What about the population there?",
    stream=True,
    session_id=SESSION_ID,
)

# Turn 3 — summary, uses history context
agent.print_response(
    "Summarize everything you told me about Tokyo",
    stream=True,
    session_id=SESSION_ID,
)

print(f"\nSession ID: {SESSION_ID}")
print("Check the DB to see tool calls stored in session history.")
