"""Run `pip install duckduckgo-search openai` to install dependencies."""

from agno.agent import Agent
from agno.storage.yaml import YamlStorage
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    storage=YamlStorage(dir_path="tmp/agent_sessions_yaml"),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
