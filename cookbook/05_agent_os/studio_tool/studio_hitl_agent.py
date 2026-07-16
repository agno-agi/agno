"""StudioTools + human-in-the-loop -- ask before building, confirm before creating.

The studio agent composes new agents from registry primitives, but it never
guesses. Three HITL mechanisms work together:

1. UserFeedbackTools (ask_user): when the user has not said which tools the
   new agent needs, the studio agent pauses with a structured multi-select
   question built from the registry tool names.
2. UserControlFlowTools (get_user_input): free-text details such as the new
   agent's instructions are collected with a user-input pause.
3. requires_confirmation on create_agent: before anything is persisted, the
   run pauses again so the user can approve or reject the exact create call.

The demo sends a deliberately underspecified request ("Create an agent called
'research-buddy'") so you can watch the pauses happen:

    Run -> paused (pick tools / provide instructions) -> continue
        -> paused (confirm create_agent?) -> continue -> created

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/studio_tool/studio_hitl_agent.py
"""

from pathlib import Path
from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.function import UserInputField
from agno.tools.hackernews import HackerNewsTools
from agno.tools.studio import StudioTools
from agno.tools.user_control_flow import UserControlFlowTools
from agno.tools.user_feedback import UserFeedbackTools

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

db = SqliteDb(id="studio-hitl-db", db_file=str(DB_DIR / "studio_hitl.db"))

registry = Registry(
    name="Studio HITL Registry",
    tools=[DuckDuckGoTools(), HackerNewsTools(), CalculatorTools()],
    models=[
        OpenAIResponses(id="gpt-5.5"),
        Claude(id="claude-sonnet-4-6"),
    ],
    dbs=[db],
)

studio_agent = Agent(
    name="Studio HITL",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        StudioTools(
            registry=registry,
            db=db,
            default_model_id="gpt-5.5",
            # Pause the run for explicit user approval before persisting.
            requires_confirmation_tools=["create_agent"],
        ),
        # Lets the agent ask structured multiple-choice questions.
        UserFeedbackTools(),
        # Lets the agent pause the run and ask for free-text details.
        UserControlFlowTools(),
    ],
    instructions=[
        "You help the user compose new agents from registry primitives.",
        "Call list_tools and list_models first so you know what is available.",
        "NEVER guess or invent missing details.",
        "If the user did not say which tools the new agent needs, use ask_user with one "
        "multi_select question whose options are ONLY the exact tool names returned by "
        "list_tools -- never include your own toolkits as options.",
        "If the user did not provide instructions for the new agent, use get_user_input "
        "to ask for them as free text.",
        "Only call create_agent once the user has supplied tools and instructions, and "
        "pass the exact tool names the user chose.",
        "After creating a component, report its id, name, model and tools.",
    ],
    db=db,
    markdown=True,
)


def handle_user_input(input_schema: List[UserInputField]) -> None:
    """Prompt the user on the console for every unanswered field."""
    print("\nThe studio agent needs more information:")
    for field in input_schema:
        if field.value is not None:
            continue
        print(f"\nField: {field.name}")
        if field.description:
            print(f"Description: {field.description}")
        field.value = input("Your answer: ")


def handle_user_feedback(requirement) -> None:
    """Render structured questions and collect the user's selections."""
    selections = {}
    for question in requirement.user_feedback_schema or []:
        print(f"\n{question.header or 'Question'}: {question.question}")
        options = question.options or []
        for i, opt in enumerate(options, 1):
            desc = f" - {opt.description}" if opt.description else ""
            print(f"  {i}. {opt.label}{desc}")

        if question.multi_select:
            raw = input("Select options (comma-separated numbers): ")
            indices = [
                int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()
            ]
        else:
            raw = input("Select an option (number): ")
            indices = [int(raw.strip()) - 1] if raw.strip().isdigit() else []
        selected = [options[i].label for i in indices if 0 <= i < len(options)]

        selections[question.question] = selected
        print(f"Selected: {selected}")
    requirement.provide_user_feedback(selections)


def handle_confirmation(requirement) -> None:
    """Show the pending tool call and ask the user to approve it."""
    tool = requirement.tool_execution
    print("\nThe studio agent wants to run a tool that requires confirmation:")
    print(f"Tool: {tool.tool_name}")
    print(f"Args: {tool.tool_args}")
    answer = input("Approve? (y/n): ").strip().lower()
    if answer == "y":
        requirement.confirm()
    else:
        requirement.reject(
            "The user rejected this call. Ask what should change instead."
        )


if __name__ == "__main__":
    # Deliberately underspecified: no tools, no instructions. The agent must ask.
    run_response = studio_agent.run("Create an agent called 'research-buddy'.")

    while run_response.is_paused:
        for requirement in run_response.active_requirements:
            if requirement.needs_user_feedback:
                handle_user_feedback(requirement)
            elif requirement.needs_user_input:
                handle_user_input(requirement.user_input_schema or [])
            elif requirement.needs_confirmation:
                handle_confirmation(requirement)

        run_response = studio_agent.continue_run(
            run_id=run_response.run_id,
            requirements=run_response.requirements,
        )

    print("\n--- Final response ---")
    print(run_response.content)
