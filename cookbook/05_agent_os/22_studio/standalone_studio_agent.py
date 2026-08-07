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
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioAccess, StudioAction, StudioTools
from agno.tools.studio_schema import ModelRef

# ---------------------------------------------------------------------------
# Create Standalone Studio Agent
# ---------------------------------------------------------------------------

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

STUDIO_ADMIN_USER_ID = "studio-admin"


def authorize_studio_admin(
    run_context: RunContext,
    _access: StudioAccess,
    _action: StudioAction,
) -> bool:
    """Limit the administrative Studio surface to the demo admin."""
    return run_context.user_id == STUDIO_ADMIN_USER_ID


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
            authorize=authorize_studio_admin,
            default_model=ModelRef(
                id="gpt-5.5",
                provider="OpenAI",
                name="OpenAIResponses",
            ),
        )
    ],
    instructions=[
        "Follow the requested StudioTools sequence exactly.",
        "Copy exact ModelRef and ToolRef values returned by discovery.",
        "Creates are drafts unless save_as='published' is explicit.",
        "Use the returned version and current version as lifecycle CAS guards.",
        "Do not stop until the requested draft has been published.",
    ],
    db=db,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Standalone Studio Lifecycle
# ---------------------------------------------------------------------------


def continue_expected_lifecycle(
    run: RunOutput,
    component_id: str,
) -> RunOutput:
    """Confirm and continue only the exact lifecycle requested by the demo."""
    expected_actions = [
        ("create_agent", None, None),
        ("publish_component", 1, None),
        ("edit_agent", None, 1),
        ("publish_component", 2, 1),
    ]
    rounds = 0
    confirmed_actions: list[str] = []
    while run.is_paused:
        active_requirements = run.active_requirements
        if not active_requirements:
            raise RuntimeError("Paused Studio run returned no active requirements")

        for requirement in active_requirements:
            if len(confirmed_actions) >= len(expected_actions):
                raise RuntimeError(f"Unexpected extra Studio pause: {requirement}")
            tool = requirement.tool_execution
            tool_args = tool.tool_args if tool is not None else None
            expected_name, expected_version, expected_current = expected_actions[
                len(confirmed_actions)
            ]
            if (
                not requirement.needs_confirmation
                or tool is None
                or tool.tool_name != expected_name
                or not isinstance(tool_args, dict)
            ):
                raise RuntimeError(f"Unexpected Studio pause: {requirement}")

            if expected_name == "create_agent":
                request = tool_args.get("request")
                valid_args = (
                    isinstance(request, dict)
                    and request.get("component_id") == component_id
                    and tool_args.get("save_as", "draft") == "draft"
                )
            elif expected_name == "edit_agent":
                valid_args = (
                    tool_args.get("component_id") == component_id
                    and tool_args.get("expected_version") == expected_current
                    and tool_args.get("save_as", "draft") == "draft"
                )
            else:
                valid_args = (
                    tool_args.get("component_id") == component_id
                    and tool_args.get("version") == expected_version
                    and tool_args.get("expected_current_version") == expected_current
                )
            if not valid_args:
                raise RuntimeError(f"Unexpected {expected_name} arguments: {tool_args}")

            print(f"Confirming {expected_name}: {tool_args}")
            requirement.confirm()
            confirmed_actions.append(expected_name)

        run = studio_agent.continue_run(
            run_id=run.run_id,
            requirements=run.requirements,
            user_id=STUDIO_ADMIN_USER_ID,
        )
        rounds += 1
        if rounds > 6:
            raise RuntimeError(
                "Studio Agent did not finish after six lifecycle continuations"
            )
    if len(confirmed_actions) != len(expected_actions):
        raise RuntimeError(
            f"Expected confirmations {[action[0] for action in expected_actions]}, "
            f"got {confirmed_actions}"
        )
    return run


def run_studio_lifecycle() -> None:
    """Create, edit, inspect, and publish one versioned Agent."""
    component_id = f"studio-math-tutor-{uuid4().hex[:8]}"
    response = studio_agent.run(
        (
            "Complete this exact sequence without asking follow-up questions: "
            "call list_models and list_tools; "
            "call create_agent with an AgentCreate request whose component_id is "
            f"'{component_id}', name is 'Studio Math Tutor', instructions are "
            "'Teach arithmetic step by step.', model is the exact discovered "
            "Claude ModelRef, and tools contains the exact calculator toolkit "
            "ToolRef; keep the default draft; "
            f"call publish_component for '{component_id}' with version=1 and "
            "expected_current_version=null; "
            f"call get_agent for '{component_id}'; "
            f"call edit_agent for '{component_id}' with expected_version=1 and an "
            "AgentPatch that changes instructions to 'Teach arithmetic step by "
            "step and explain every intermediate result.'; "
            f"call list_versions for '{component_id}'; "
            f"then call publish_component for '{component_id}' with version=2 and "
            "expected_current_version=1. Do not run the new agent."
        ),
        user_id=STUDIO_ADMIN_USER_ID,
    )
    response = continue_expected_lifecycle(response, component_id)

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
