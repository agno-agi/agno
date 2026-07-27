"""
Resolve three workflow HITL pauses through AgentOS
==================================================

One OS-served workflow pauses before a sensitive step, pauses again to collect
step input, then pauses after producing a draft so a human can review its
output. The HTTP client resolves every returned ``step_requirements`` payload
through the workflow ``continue`` route.

This file is the AgentOS transport view. See
``cookbook/04_workflows/08_human_in_the_loop`` for the full workflow HITL
primitive matrix.

Prerequisites: none
Run: .venvs/demo/bin/python cookbook/05_agent_os/05_human_in_the_loop/workflow_hitl.py
Try: Run this file with --demo in another terminal
"""

import argparse
import json
from typing import Any

import httpx
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.workflow import HumanReview, OnReject
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, UserInputField
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create HITL Workflow
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
WORKFLOW_ID = "release-review-workflow"
SESSION_ID = "workflow-hitl-demo"


def inspect_release(step_input: StepInput) -> StepOutput:
    """Inspect the release supplied as workflow input."""
    release = step_input.input or "unknown release"
    return StepOutput(content=f"Inspected release: {release}")


def choose_environment(step_input: StepInput) -> StepOutput:
    """Read the environment supplied by the workflow continuation."""
    user_input = (
        step_input.additional_data.get("user_input", {})
        if step_input.additional_data
        else {}
    )
    environment = user_input.get("environment", "unset")
    return StepOutput(content=f"Selected environment: {environment}")


def draft_change_record(step_input: StepInput) -> StepOutput:
    """Create the output that the final HITL pause reviews."""
    previous = step_input.previous_step_content or "No environment selected"
    return StepOutput(content=f"Draft change record\n{previous}")


db = SqliteDb(
    id="workflow-hitl-db",
    db_file="tmp/agent_os_workflow_hitl.db",
)

release_workflow = Workflow(
    id=WORKFLOW_ID,
    name="Release Review Workflow",
    db=db,
    steps=[
        Step(
            name="Inspect Release",
            executor=inspect_release,
            requires_confirmation=True,
            confirmation_message="Inspect this release now?",
            on_reject=OnReject.cancel,
        ),
        Step(
            name="Choose Environment",
            executor=choose_environment,
            requires_user_input=True,
            user_input_message="Choose the deployment environment.",
            user_input_schema=[
                UserInputField(
                    name="environment",
                    field_type="str",
                    description="Deployment environment",
                    required=True,
                    allowed_values=["staging", "production"],
                )
            ],
        ),
        Step(
            name="Draft Change Record",
            executor=draft_change_record,
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Approve the drafted change record.",
                on_reject=OnReject.cancel,
            ),
        ),
    ],
)

agent_os = AgentOS(
    id="workflow-hitl-os",
    db=db,
    workflows=[release_workflow],
)
app = agent_os.get_app()


def resolve_step_requirements(
    requirements: list[dict[str, Any]],
) -> list[str]:
    """Confirm, fill, or approve each active workflow requirement."""
    resolutions: list[str] = []
    for requirement in requirements:
        if (
            requirement.get("requires_output_review")
            and requirement.get("confirmed") is None
        ):
            requirement["confirmed"] = True
            resolutions.append("output review")
        elif (
            requirement.get("requires_confirmation")
            and requirement.get("confirmed") is None
        ):
            requirement["confirmed"] = True
            resolutions.append("step confirmation")
        elif requirement.get("requires_user_input") and not requirement.get(
            "user_input"
        ):
            requirement["user_input"] = {"environment": "staging"}
            for field in requirement.get("user_input_schema") or []:
                if field["name"] == "environment":
                    field["value"] = "staging"
            resolutions.append("step user input")
    return resolutions


def run_demo() -> None:
    """Continue the workflow until all three HITL pauses are resolved."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        response = client.post(
            f"/workflows/{WORKFLOW_ID}/runs",
            data={
                "message": "billing version 4.0.0",
                "session_id": SESSION_ID,
                "stream": "false",
            },
        )
        response.raise_for_status()
        run = response.json()
        rounds = 0

        while run["status"] == "PAUSED":
            requirements = run.get("step_requirements") or []
            if not requirements:
                raise RuntimeError("The paused workflow returned no step requirements")
            resolved = resolve_step_requirements(requirements)
            if not resolved:
                raise RuntimeError("The client did not recognize the workflow pause")
            rounds += 1
            print(f"Round {rounds}: resolved {', '.join(resolved)}")

            response = client.post(
                f"/workflows/{WORKFLOW_ID}/runs/{run['run_id']}/continue",
                data={
                    "step_requirements": json.dumps(requirements),
                    "session_id": run["session_id"],
                    "stream": "false",
                },
            )
            response.raise_for_status()
            run = response.json()
            if rounds > 3:
                raise RuntimeError("The workflow did not finish after three pauses")

        if run["status"] != "COMPLETED":
            raise RuntimeError(f"Expected COMPLETED, got {run['status']}")
        if rounds != 3:
            raise RuntimeError(f"Expected three workflow pauses, observed {rounds}")
        print(f"Final status: {run['status']}")
        print(f"Result: {run.get('content')}")


# ---------------------------------------------------------------------------
# Run HITL Workflow
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the HTTP client against a server already listening on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, port=7777)
