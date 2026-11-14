"""
Standalone usage of a Google ADK agent with Agno's .run() and .print_response() methods.

Requirements:
    pip install google-adk
    export GOOGLE_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/google_adk/google_adk_basic.py
"""

from agno.agents.google_adk import GoogleADKAgent
from google.adk.agents import LlmAgent

# ----- Build an ADK agent -----
adk_agent = LlmAgent(
    name="assistant",
    model="gemini-3.7-flash",
    instruction="You are a concise assistant. Answer in a short paragraph.",
)

# ----- Wrap it for Agno -----
agent = GoogleADKAgent(
    name="ADK Assistant",
    agent=adk_agent,
)

# Use .print_response() just like a native Agno agent
agent.print_response("What is quantum computing?", stream=True)
