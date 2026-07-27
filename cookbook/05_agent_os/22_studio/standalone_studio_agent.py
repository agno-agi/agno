"""
Compose and version an Agent without starting AgentOS
=====================================================

StudioTools can persist components directly through a synchronous database. This
standalone Agent discovers registry primitives, creates an Agent, edits it into
a draft, inspects its versions, and publishes the draft.

Prerequisites: ANTHROPIC_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/standalone_studio_agent.py
Try: ask the Studio Agent to roll back to the first published version
"""

from pathlib import Path
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioTools

# ---------------------------------------------------------------------------
# Create Standalone Studio Agent
# ---------------------------------------------------------------------------

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

db = SqliteDb(
    id="standalone-studio-db",
    db_file=str(DB_DIR / "standalone_studio.db"),
)

registry = Registry(
    name="Standalone Studio Registry",
    tools=[CalculatorTools()],
    models=[
        OpenAIResponses(id="gpt-5.5"),
        Claude(id="claude-sonnet-4-6"),
    ],
    dbs=[db],
)

studio_agent = Agent(
    id="standalone-studio-agent",
    name="Standalone Studio Agent",
    model=Claude(id="claude-sonnet-4-6"),
    tools=[
        StudioTools(
            registry=registry,
            db=db,
            default_model_id="gpt-5.5",
            versions=True,
        )
    ],
    instructions=[
        "Follow the requested StudioTools sequence exactly.",
        "Use only exact model and tool names returned by discovery.",
        "Do not stop until the requested draft has been published.",
    ],
    db=db,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Standalone Studio Lifecycle
# ---------------------------------------------------------------------------


def run_studio_lifecycle() -> None:
    """Create, edit, inspect, and publish one versioned Agent."""
    component_id = f"studio-math-tutor-{uuid4().hex[:8]}"
    response = studio_agent.run(
        (
            "Complete this exact sequence without asking follow-up questions: "
            "call list_models and list_tools; "
            f"create an agent named '{component_id}' with model "
            "'claude-sonnet-4-6', tool 'calculator', and instructions "
            "'Teach arithmetic step by step.'; "
            f"call get_agent for '{component_id}'; "
            "edit its instructions to 'Teach arithmetic step by step and explain "
            "every intermediate result.'; "
            f"call list_versions for '{component_id}'; "
            f"then publish_component for '{component_id}'. Do not run the new agent."
        )
    )

    component = db.get_component(component_id)
    versions = db.list_configs(component_id, include_config=False)
    if component is None:
        raise RuntimeError("StudioTools did not persist the requested Agent")
    if component.get("current_version") != 2:
        raise RuntimeError(
            f"Expected published version 2, got {component.get('current_version')}"
        )
    if [version.get("stage") for version in versions] != ["published", "published"]:
        raise RuntimeError(f"Expected two published versions, got {versions}")

    print(f"Studio run: {response.run_id}")
    print(f"Component: {component_id}")
    print(f"Current version: {component['current_version']}")
    print(f"Version stages: {[version['stage'] for version in versions]}")
    print(response.content)


if __name__ == "__main__":
    run_studio_lifecycle()
