"""Serve an AgentOS whose manager can build and run agents.

Ask OS Manager: "Create a calculator agent named Budget Helper."
Then ask: "Run Budget Helper: what is 15% of 240?"

The registry supplies the model and tools for new agents. It also includes
functions for workflows that convert JSON and CSV without a model call.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_builds_agents.py
"""

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.workflow.functions import csv_to_markdown_table, extract_json, json_to_csv

# Choose what the builder can use in new agents and workflows.
registry = Registry(
    models=[OpenAIResponses(id="gpt-5.6-luna")],
    tools=[CalculatorTools()],
    functions=[extract_json, json_to_csv, csv_to_markdown_table],
)

agent_os = AgentOS(
    name="Manager builds agents",
    db=SqliteDb(db_file="tmp/manager_builds.db"),
    registry=registry,
    # Use the first model in the registry for the manager too.
    manager=True,
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="manager_builds_agents:app", reload=True)
