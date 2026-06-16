"""Standalone StudioTool agent (no AgentOS).

A simple Agent that uses StudioTool to build, edit, version, and run other
agents backed by a local SQLite database. No AgentOS server, no REST, just
in-process composition.

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/studio_tool/standalone_studio_agent.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.studio import StudioTool

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

db = SqliteDb(id="standalone-studio-db", db_file=str(DB_DIR / "standalone_studio.db"))

registry = Registry(
    name="Standalone Studio Registry",
    tools=[DuckDuckGoTools(), CalculatorTools()],
    models=[OpenAIResponses(id="gpt-5.5"), Claude(id="claude-sonnet-4-6")],
    dbs=[db],
)

studio_agent = Agent(
    name="Studio",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[
        StudioTool(registry=registry, db=db, default_model_id="gpt-5.5", versions=True)
    ],
    instructions=[
        "You help the user compose agents, teams, and workflows from registry primitives.",
        "Before calling create_*, restate the exact tool names you plan to pass.",
        "Before calling edit_*, call get_agent/get_team/get_workflow first and confirm what changes.",
        "After any edit, remind the user that changes are in a draft until publish_component is called.",
    ],
    db=db,
    markdown=True,
)


if __name__ == "__main__":
    studio_agent.print_response(
        "First, create an agent called 'math-tutor' that uses claude-sonnet-4-6 and the calculator "
        "toolkit with instructions 'Teach math step by step.' "
        "Then edit it to add this to its instructions: 'Explain each intermediate result before moving on.' "
        "Then list_versions for math-tutor so I can see the draft. "
        "Finally, publish_component('math-tutor') to publish the draft."
    )
