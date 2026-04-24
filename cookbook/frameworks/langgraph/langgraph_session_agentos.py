"""
LangGraph agent with tools served through AgentOS.

A LangGraph ReAct-style agent with web search, served through
the same AgentOS runtime used for native Agno agents.

Requirements:
    pip install langgraph langchain-openai langchain-community

Usage:
    python cookbook/frameworks/langgraph/langgraph_tools_agentos.py

Then call the API:
    # Streaming
    curl -X POST http://localhost:7777/agents/langgraph-search/runs \\
        -F "message=What are the latest AI agent developments?" \\
        -F "stream=true" \\
        --no-buffer

    # Non-streaming
    curl -X POST http://localhost:7777/agents/langgraph-search/runs \\
        -F "message=What is quantum computing?" \\
        -F "stream=false"

    # List agents
    curl http://localhost:7777/agents
"""

from agno.agents.langgraph import LangGraphAgent
from agno.db.postgres import PostgresDb
from agno.os.app import AgentOS
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

# ----- Tools -----
search_tool = DuckDuckGoSearchResults(max_results=3)
tools = [search_tool]

# ----- Build the LangGraph with tools -----
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

# ----- Wrap for AgentOS -----
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = LangGraphAgent(
    name="LangGraph Search Agent",
    description="A LangGraph agent with web search, served through AgentOS",
    graph=compiled,
    db=db,
)

# ----- Serve through AgentOS -----
agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="langgraph_tools_agentos:app", reload=True)
