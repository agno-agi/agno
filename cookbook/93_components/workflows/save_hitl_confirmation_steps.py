"""
Save HITL Confirmation Workflow Steps
======================================

Demonstrates creating a workflow with HITL confirmation on steps,
saving it to the database, and loading it back. The HITL config
(requires_confirmation, confirmation_message, on_reject) round-trips
through to_dict / from_dict automatically.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.registry import Registry
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow, get_workflow_by_id

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
research_agent = Agent(
    id="hitl-confirm-researcher",
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the given topic and provide key findings.",
)

processor_agent = Agent(
    id="hitl-confirm-processor",
    name="Processor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Process and validate the research data.",
)

writer_agent = Agent(
    id="hitl-confirm-writer",
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Write a summary report from processed research.",
)

# ---------------------------------------------------------------------------
# Registry (required to resolve agents when loading from DB)
# ---------------------------------------------------------------------------
registry = Registry(
    name="HITL Confirmation Registry",
    agents=[research_agent, processor_agent, writer_agent],
    dbs=[db],
)

# ---------------------------------------------------------------------------
# Create Workflow with HITL Confirmation
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="HITL Confirmation Workflow",
    description="Workflow with step-level confirmation before processing",
    steps=[
        Step(
            name="Research",
            description="Gather research data",
            agent=research_agent,
        ),
        Step(
            name="ProcessData",
            description="Process and validate research (requires confirmation)",
            agent=processor_agent,
            requires_confirmation=True,
            confirmation_message="Research complete. Ready to process data. Proceed?",
            on_reject=OnReject.skip,
        ),
        Step(
            name="WriteReport",
            description="Generate final report",
            agent=writer_agent,
        ),
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Save, Load, and Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Save workflow to database
    print("Saving workflow with HITL confirmation config...")
    version = workflow.save(db=db)
    print(f"Saved as version {version}")

    # Load workflow back from database
    print("\nLoading workflow...")
    loaded_workflow = get_workflow_by_id(
        db=db,
        id="hitl-confirmation-workflow",
        registry=registry,
    )

    if loaded_workflow is None:
        print("Workflow not found")
        exit(1)

    print("Workflow loaded successfully!")
    print(f"  Name: {loaded_workflow.name}")
    print(f"  Steps: {len(loaded_workflow.steps) if loaded_workflow.steps else 0}")

    # Verify HITL config survived the round-trip
    if loaded_workflow.steps:
        for step in loaded_workflow.steps:
            if hasattr(step, "requires_confirmation") and step.requires_confirmation:
                print(f"\n  Step '{step.name}' has HITL config:")
                print(f"    requires_confirmation: {step.requires_confirmation}")
                print(f"    confirmation_message: {step.confirmation_message}")
                print(f"    on_reject: {step.on_reject}")

    # Run the loaded workflow
    print("\nRunning loaded workflow...")
    run_output = loaded_workflow.run("Benefits of renewable energy")

    # Handle HITL pause
    while run_output.is_paused:
        for requirement in run_output.steps_requiring_confirmation:
            print(f"\n[HITL] Step '{requirement.step_name}' requires confirmation")
            print(f"[HITL] {requirement.confirmation_message}")

            user_input = input("\nContinue? (yes/no): ").strip().lower()

            if user_input in ("yes", "y"):
                requirement.confirm()
                print("[HITL] Confirmed")
            else:
                requirement.reject()
                print("[HITL] Rejected - step will be skipped")

        run_output = loaded_workflow.continue_run(run_output)

    print(f"\nStatus: {run_output.status}")
    print(f"Output:\n{run_output.content}")
