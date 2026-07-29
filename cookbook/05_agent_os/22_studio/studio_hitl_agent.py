"""
Resolve Studio composition pauses in the console
================================================

This standalone Studio Agent gathers a structured tool choice, requests
free-text instructions, and pauses again before create_agent persists anything.
The console resolves RunRequirement objects and continues the same run.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_hitl_agent.py
Try: add --auto to resolve all three pauses with deterministic demo answers
"""

import argparse
from pathlib import Path
from typing import Any
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioTools
from agno.tools.user_control_flow import UserControlFlowTools
from agno.tools.user_feedback import UserFeedbackTools

# ---------------------------------------------------------------------------
# Create Console HITL Studio Agent
# ---------------------------------------------------------------------------

AUTO_INSTRUCTIONS = "Explain reliable research methods in concise steps."

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

db = SqliteDb(
    id="studio-hitl-console-db",
    db_file=str(DB_DIR / "studio_hitl_console.db"),
)

registry = Registry(
    name="Console HITL Studio Registry",
    tools=[CalculatorTools()],
    models=[
        OpenAIResponses(id="gpt-5.5"),
        Claude(id="claude-sonnet-4-6"),
    ],
    dbs=[db],
)

studio_agent = Agent(
    id="studio-hitl-console-agent",
    name="Console HITL Studio Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        StudioTools(
            registry=registry,
            db=db,
            default_model_id="gpt-5.5",
            requires_confirmation_tools=["create_agent"],
        ),
        UserFeedbackTools(),
        UserControlFlowTools(),
    ],
    instructions=[
        "Help the user compose one Agent from registry primitives.",
        "Call list_tools, list_models, and list_dbs first.",
        "If tools are missing, call ask_user with one multi-select question whose "
        "options are exact names returned by list_tools.",
        "If instructions are missing, call get_user_input with one string field.",
        "Do not combine the missing tool and instruction questions in chat.",
        "Use the exact database id returned by list_dbs when creating the Agent. "
        "Never pass an empty string or the word 'default' as db_id.",
        "Call create_agent only after both answers are available.",
    ],
    db=db,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Console HITL Studio Agent
# ---------------------------------------------------------------------------


def resolve_feedback(requirement: Any, auto: bool) -> None:
    """Resolve one structured feedback requirement."""
    selections: dict[str, list[str]] = {}
    for question in requirement.user_feedback_schema or []:
        options = question.options or []
        labels = [option.label for option in options]
        print(f"\n{question.header or 'Question'}: {question.question}")
        for index, option in enumerate(options, 1):
            print(f"  {index}. {option.label}")

        if auto:
            selected = ["calculator"] if "calculator" in labels else labels[:1]
        else:
            raw = input("Select options (comma-separated numbers): ")
            indices = [
                int(value.strip()) - 1
                for value in raw.split(",")
                if value.strip().isdigit()
            ]
            selected = [labels[index] for index in indices if 0 <= index < len(labels)]
        selections[question.question] = selected
        print(f"Selected: {selected}")
    requirement.provide_user_feedback(selections)


def resolve_input(requirement: Any, auto: bool) -> None:
    """Resolve every free-text field in one user-input requirement."""
    values: dict[str, str] = {}
    for field in requirement.user_input_schema or []:
        if field.value is not None:
            continue
        print(f"\nInput needed: {field.name}")
        values[field.name] = AUTO_INSTRUCTIONS if auto else input("Your answer: ")
    requirement.provide_user_input(values)


def resolve_confirmation(requirement: Any, auto: bool) -> bool:
    """Approve or reject the pending create_agent call."""
    tool = requirement.tool_execution
    if tool is None:
        raise RuntimeError("Confirmation requirement did not include a tool")
    print(f"\nConfirmation needed: {tool.tool_name}")
    print(f"Arguments: {tool.tool_args}")
    approved = auto or input("Approve? (y/n): ").strip().lower() == "y"
    if approved:
        requirement.confirm()
    else:
        requirement.reject("The user rejected this component.")
    return approved


def run_console_demo(auto: bool = False) -> None:
    """Resolve feedback, input, and confirmation pauses in one run."""
    component_id = f"console-research-buddy-{uuid4().hex[:8]}"
    run = studio_agent.run(f"Create an agent called '{component_id}'.")
    observed: list[str] = []
    confirmation_approved: bool | None = None
    rounds = 0

    while run.is_paused:
        active_requirements = run.active_requirements
        if not active_requirements:
            raise RuntimeError("Paused run returned no active requirements")
        for requirement in active_requirements:
            if requirement.needs_user_feedback:
                resolve_feedback(requirement, auto)
                observed.append("user_feedback")
            elif requirement.needs_user_input:
                resolve_input(requirement, auto)
                observed.append("user_input")
            elif requirement.needs_confirmation:
                confirmation_approved = resolve_confirmation(requirement, auto)
                observed.append("confirmation")
            else:
                raise RuntimeError(f"Unsupported requirement: {requirement}")

        run = studio_agent.continue_run(
            run_id=run.run_id,
            requirements=run.requirements,
        )
        rounds += 1
        if rounds > 6:
            raise RuntimeError(
                "Studio Agent did not finish after six continuation rounds"
            )

    expected = ["user_feedback", "user_input", "confirmation"]
    if observed != expected:
        raise RuntimeError(f"Expected pause sequence {expected}, observed {observed}")
    component = db.get_component(component_id)
    if confirmation_approved and component is None:
        raise RuntimeError("Confirmed create_agent call did not persist the component")
    if confirmation_approved is False and component is not None:
        raise RuntimeError(
            "Rejected create_agent call unexpectedly persisted a component"
        )

    print(f"\nPause sequence: {observed}")
    print(f"Final run: {run.run_id} -> {run.status.value}")
    print(
        f"Component outcome: {component_id} "
        f"({'created' if component is not None else 'not created'})"
    )
    print(run.content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Resolve each pause with deterministic demo answers.",
    )
    args = parser.parse_args()
    run_console_demo(auto=args.auto)
