"""Run `pip install duckduckgo-search openai` to install dependencies."""

from agno.agent import Agent
from agno.storage.agent.json import JsonAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    storage=JsonAgentStorage(dir_path="tmp/agent_sessions_json"),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
