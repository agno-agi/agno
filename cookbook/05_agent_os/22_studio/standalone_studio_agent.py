"""
Compose and version an Agent without starting AgentOS
=====================================================

StudioTools can persist components directly through a synchronous database.
This standalone Agent walks the full 3.0 ladder: create (a draft), validate,
preview the draft with run_agent(version=1), publish, edit (a new draft
version), and publish again. A second section calls the same tools directly
from Python to compose a workflow with a compound loop step and shows the
StudioResult envelope every tool returns.

Prerequisites: ANTHROPIC_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/standalone_studio_agent.py
Try: ask the Studio Agent to roll back with set_current_version
"""

import json
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

# versions=True is the default: constructing StudioTools gives the full draft
# lifecycle (list_versions, publish_component, set_current_version,
# delete_version) without opting in. Every create_* writes a DRAFT unless
# publish=True; only a published version serves runs and schedules.
studio_tools = StudioTools(
    registry=registry,
    db=db,
    default_model_id="gpt-5.5",
)

studio_agent = Agent(
    id="standalone-studio-agent",
    name="Standalone Studio Agent",
    model=Claude(id="claude-sonnet-4-6"),
    tools=[studio_tools],
    instructions=[
        "Follow the requested StudioTools sequence exactly.",
        "Use only exact model and tool names returned by discovery.",
        "Do not stop until the requested versions have been published.",
    ],
    db=db,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Standalone Studio Lifecycle
# ---------------------------------------------------------------------------


def run_studio_lifecycle() -> None:
    """Walk create -> validate -> preview -> publish -> edit -> publish."""
    component_id = f"studio-math-tutor-{uuid4().hex[:8]}"
    response = studio_agent.run(
        (
            "Complete this exact sequence without asking follow-up questions: "
            "call list_models and list_tools; "
            f"create an agent named '{component_id}' with model "
            "'claude-sonnet-4-6', tool 'calculator', and instructions "
            "'Teach arithmetic step by step.' (this writes DRAFT version 1); "
            f"call validate_component for '{component_id}'; "
            f"preview the draft by calling run_agent for '{component_id}' with "
            "version 1 and the message 'What is 6 times 7?'; "
            f"call publish_component for '{component_id}'; "
            "edit its instructions to 'Teach arithmetic step by step and explain "
            "every intermediate result.' (this appends DRAFT version 2); "
            f"call list_versions for '{component_id}'; "
            f"then publish_component for '{component_id}' again. "
            "Do not run the published agent."
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


# ---------------------------------------------------------------------------
# Compose a workflow directly (no wielding model)
# ---------------------------------------------------------------------------


def compose_workflow_directly() -> None:
    """Call the toolkit as plain Python and read the StudioResult envelope.

    Every StudioTools tool returns one JSON envelope: {ok, status, data,
    error: {code, message, details, retryable}, warnings}. Branch on
    error.code, never on message text.
    """
    suffix = uuid4().hex[:8]
    created = json.loads(
        studio_tools.create_agent(
            name=f"Draft Checker {suffix}",
            instructions="Check one arithmetic claim and answer true or false.",
            tool_names=["calculator"],
            publish=True,
        )
    )
    if not created["ok"]:
        raise RuntimeError(f"create_agent failed: {created['error']['code']}")
    checker_id = created["data"]["id"]
    print(f"Created agent: {checker_id} (stage: {created['data']['stage']})")

    # Workflow steps are WorkflowStepSpec-shaped dicts. A plain step names
    # exactly one executor; compound steps (parallel, loop, condition,
    # router, steps) nest further steps of the same shape.
    workflow = json.loads(
        studio_tools.create_workflow(
            name=f"Claim Review {suffix}",
            description="Check a claim, then re-check until it settles.",
            steps=[
                {"name": "first-pass", "agent_id": checker_id},
                {
                    "type": "loop",
                    "name": "re-check",
                    "max_iterations": 2,
                    "steps": [{"name": "check-again", "agent_id": checker_id}],
                },
            ],
            publish=True,
        )
    )
    if not workflow["ok"]:
        raise RuntimeError(f"create_workflow failed: {workflow['error']['code']}")
    workflow_id = workflow["data"]["id"]
    print(f"Created workflow: {workflow_id} (steps: {workflow['data']['steps']})")

    validated = json.loads(studio_tools.validate_component(workflow_id))
    print(f"Validation: {validated['status']} (valid: {validated['data']['valid']})")

    # edit_* appends an immutable draft version; expected_version is an
    # optional compare-and-set guard against the latest version you read.
    edited = json.loads(
        studio_tools.edit_workflow(
            workflow_id,
            description="Check a claim, then re-check it up to two times.",
            expected_version=1,
        )
    )
    print(f"Edit appended draft version: {edited['data']['draft_version']}")

    # The same guard now conflicts: the latest version is no longer 1.
    stale = json.loads(
        studio_tools.edit_workflow(
            workflow_id,
            description="This edit is based on a stale read.",
            expected_version=1,
        )
    )
    if stale["ok"] or stale["error"]["code"] != "version_conflict":
        raise RuntimeError(f"Expected version_conflict, got {stale}")
    print(
        f"Stale guard refused: {stale['error']['code']} "
        f"(retryable: {stale['error']['retryable']})"
    )


if __name__ == "__main__":
    run_studio_lifecycle()
    compose_workflow_directly()
