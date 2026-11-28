"""
Google ADK Agent on AgentOS
===========================
A Google ADK agent, served through AgentOS.

Requirements:
    pip install google-adk
    export GOOGLE_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/00_quickstart/google_adk_agent.py
"""

from agno.agents.google_adk import GoogleADKAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from google.adk.agents import LlmAgent

adk_agent = LlmAgent(
    name="assistant",
    model="gemini-3.7-flash",
    instruction="You are a helpful assistant.",
)

agent = GoogleADKAgent(
    name="ADK Assistant",
    agent=adk_agent,
)

agent_os = AgentOS(
    agents=[agent],
    tracing=True,
    db=SqliteDb(db_file="tmp/agentos.db"),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="google_adk_agent:app", reload=True)
