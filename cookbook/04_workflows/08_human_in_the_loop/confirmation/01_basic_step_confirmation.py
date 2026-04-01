"""
Basic Step Confirmation Example

This example demonstrates how to pause a workflow for user confirmation
before executing a step. The user can either:
- Confirm: Step executes and workflow continues
- Reject with on_reject=OnReject.cancel (default): Workflow is cancelled
- Reject with on_reject=OnReject.skip: Step is skipped and workflow continues with next step
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Create agents for each step
fetch_agent = Agent(
    name="Fetcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You fetch and summarize data. Return a brief summary of what data you would fetch.",
)

process_agent = Agent(
    name="Processor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You process data. Describe what processing you would do on the input.",
)

save_agent = Agent(
    name="Saver",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You save results. Confirm that you would save the processed data.",
)

# Create a workflow with a step that requires confirmation
# on_reject="skip" means if user rejects, skip this step and continue with next
workflow = Workflow(
    name="data_processing",
    db=SqliteDb(
        db_file="tmp/workflow_hitl.db"
    ),  # Required for HITL to persist session state
    steps=[
        Step(
            name="fetch_data",
            agent=fetch_agent,
        ),
        Step(
            name="process_data",
            agent=process_agent,
            requires_confirmation=True,
            confirmation_message="About to process sensitive data. Confirm?",
            on_reject=OnReject.skip,  # If rejected, skip this step and continue with save_results
        ),
        Step(
            name="save_results",
            agent=save_agent,
        ),
    ],
)

# Run the workflow
run_output = workflow.run("Process user data")

# Check if workflow is paused
if run_output.is_paused:
    for requirement in run_output.steps_requiring_confirmation:
        print(f"\nStep '{requirement.step_name}' requires confirmation")
        print(f"Message: {requirement.confirmation_message}")

        # Wait for actual user input
        user_input = input("\nDo you want to continue? (yes/no): ").strip().lower()

        if user_input in ("yes", "y"):
            requirement.confirm()
            print("Step confirmed.")
        else:
            requirement.reject()
            print("Step rejected.")

    # Continue the workflow
    run_output = workflow.continue_run(run_output)

print(f"\nFinal output: {run_output.content}")
