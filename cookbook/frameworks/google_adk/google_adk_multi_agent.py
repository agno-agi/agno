"""
A Google ADK agent tree served as one Agno agent.

ADK composes agents into trees: a SequentialAgent runs its sub-agents in order,
each reading the previous step's output from session state. The whole tree is
one GoogleADKAgent; the text of every step is part of the run's content.

Requirements:
    pip install google-adk
    export GOOGLE_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/google_adk/google_adk_multi_agent.py
"""

from agno.agents.google_adk import GoogleADKAgent
from google.adk.agents import LlmAgent, SequentialAgent

# ----- Build the tree -----
researcher = LlmAgent(
    name="researcher",
    model="gemini-3.7-flash",
    instruction="List three to five key facts about the topic the user asks about, as short bullet points.",
    output_key="facts",
)

writer = LlmAgent(
    name="writer",
    model="gemini-3.7-flash",
    instruction="Write one short paragraph for a general reader using only these facts:\n{facts}",
)

pipeline = SequentialAgent(
    name="research_and_write",
    sub_agents=[researcher, writer],
)

# ----- Wrap for Agno -----
agent = GoogleADKAgent(
    name="ADK Research Pipeline",
    agent=pipeline,
)

agent.print_response("The James Webb Space Telescope", stream=True)
