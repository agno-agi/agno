"""
Run a LangGraph agent through AgentOS endpoints.

This shows how to register a LangGraph agent alongside native Agno agents
and serve them all through the same AgentOS runtime.

Requirements:
    pip install langgraph langchain-openai

Usage:
    .venvs/demo/bin/python cookbook/frameworks/langgraph_agentos.py

Then call the API:
    # Streaming
    curl -X POST http://localhost:7777/agents/langgraph-chatbot/runs \
        -F "message=What is quantum computing?" \
        -F "stream=true" \
        --no-buffer

    # Non-streaming
    curl -X POST http://localhost:7777/agents/langgraph-chatbot/runs \
        -F "message=What is quantum computing?" \
        -F "stream=false"

    # List agents
    curl http://localhost:7777/agents
"""

from agno.agents.langgraph import LangGraphAgent
from agno.os.app import AgentOS
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph


# ----- Build a LangGraph agent -----
def chatbot(state: MessagesState):
    return {"messages": [ChatOpenAI(model="gpt-5.4").invoke(state["messages"])]}


graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.set_entry_point("chatbot")
compiled = graph.compile()


# ----- Wrap for AgentOS -----
langgraph_agent = LangGraphAgent(
    name="LangGraph Chatbot",
    description="A simple chatbot built with LangGraph, served through AgentOS",
    graph=compiled,
)

# ----- Serve through AgentOS -----
agent_os = AgentOS(agents=[langgraph_agent])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="langgraph_agentos:app", reload=True)
