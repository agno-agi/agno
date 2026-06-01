"""
Save HITL Condition, Loop, and Router Steps
=============================================

Demonstrates HITL config on Condition, Loop, and Router components.
Each component type supports requires_confirmation and on_reject, and
all settings round-trip through save/load via to_dict / from_dict.

- Condition: User decides which branch to take (on_reject="else" runs else_steps)
- Loop: User confirms before starting an iterative process
- Router: User selects which routes to execute
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.registry import Registry
from agno.workflow import OnReject
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow, get_workflow_by_id

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
analysis_agent = Agent(
    id="hitl-analyst",
    name="Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Perform detailed data analysis.",
)

summary_agent = Agent(
    id="hitl-summarizer",
    name="Summarizer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Provide a quick summary of the data.",
)

research_agent = Agent(
    id="hitl-researcher",
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the given topic thoroughly.",
)

writer_agent = Agent(
    id="hitl-writer",
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Write a report from the findings.",
)


# ---------------------------------------------------------------------------
# Executor Functions (registered for serialization)
# ---------------------------------------------------------------------------
def refine_analysis(step_input: StepInput) -> StepOutput:
    """One iteration of analysis refinement."""
    return StepOutput(content="Refinement iteration complete. Quality improved.")


registry = Registry(
    name="HITL Components Registry",
    agents=[analysis_agent, summary_agent, research_agent, writer_agent],
    functions=[refine_analysis],
    dbs=[db],
)


# ---------------------------------------------------------------------------
# Create Workflow: Condition with HITL
# ---------------------------------------------------------------------------
condition_workflow = Workflow(
    name="HITL Condition Workflow",
    description="User decides between detailed analysis or quick summary",
    steps=[
        Condition(
            name="AnalysisDepth",
            description="User chooses analysis depth",
            evaluator=True,
            steps=[Step(name="DetailedAnalysis", agent=analysis_agent)],
            else_steps=[Step(name="QuickSummary", agent=summary_agent)],
            requires_confirmation=True,
            confirmation_message="Perform detailed analysis? (No = quick summary)",
            on_reject=OnReject.else_branch,
        ),
        Step(name="FinalReport", agent=writer_agent),
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Create Workflow: Loop with HITL
# ---------------------------------------------------------------------------
loop_workflow = Workflow(
    name="HITL Loop Workflow",
    description="User confirms before starting refinement loop",
    steps=[
        Step(name="InitialAnalysis", agent=analysis_agent),
        Loop(
            name="RefinementLoop",
            description="Iterative refinement (user confirms to start)",
            steps=[Step(name="Refine", executor=refine_analysis)],
            max_iterations=3,
            requires_confirmation=True,
            confirmation_message="Start iterative refinement? This runs up to 3 iterations.",
            on_reject=OnReject.skip,
        ),
        Step(name="WriteReport", agent=writer_agent),
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Create Workflow: Router with HITL
# ---------------------------------------------------------------------------
router_workflow = Workflow(
    name="HITL Router Workflow",
    description="User selects which processing routes to execute",
    steps=[
        Router(
            name="ProcessingRouter",
            description="User picks which steps to run",
            choices=[
                Step(name="Research", agent=research_agent),
                Step(name="Analysis", agent=analysis_agent),
                Step(name="Summary", agent=summary_agent),
            ],
            requires_user_input=True,
            user_input_message="Select which processing steps to run:",
            allow_multiple_selections=True,
        ),
        Step(name="WriteReport", agent=writer_agent),
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Save, Load, and Verify
# ---------------------------------------------------------------------------
WORKFLOWS = {
    "condition": (condition_workflow, "hitl-condition-workflow"),
    "loop": (loop_workflow, "hitl-loop-workflow"),
    "router": (router_workflow, "hitl-router-workflow"),
}


def save_and_verify(name: str, wf: Workflow, wf_id: str):
    """Save a workflow and verify HITL config round-trips correctly."""
    print(f"\n{'=' * 60}")
    print(f"  {name.upper()}")
    print(f"{'=' * 60}")

    # Save
    version = wf.save(db=db)
    print(f"Saved as version {version}")

    # Load
    loaded = get_workflow_by_id(db=db, id=wf_id, registry=registry)
    if loaded is None:
        print("Failed to load workflow")
        return None

    print("Loaded successfully!")
    print(f"  Steps: {len(loaded.steps) if loaded.steps else 0}")

    # Verify HITL config
    if loaded.steps:
        for step in loaded.steps:
            hitl_fields = []
            if hasattr(step, "requires_confirmation") and step.requires_confirmation:
                hitl_fields.append(f"confirmation='{step.confirmation_message}'")
                hitl_fields.append(f"on_reject={step.on_reject}")
            if hasattr(step, "requires_user_input") and step.requires_user_input:
                hitl_fields.append(f"user_input='{step.user_input_message}'")
            if hitl_fields:
                print(f"  HITL on '{step.name}': {', '.join(hitl_fields)}")

    return loaded


def run_workflow(loaded: Workflow, input_text: str):
    """Run a loaded workflow with interactive HITL handling."""
    print("\nRunning workflow...")
    run_output = loaded.run(input_text)

    while run_output.is_paused:
        # Handle confirmations
        for req in run_output.steps_requiring_confirmation:
            print(f"\n[HITL] {req.step_name}: {req.confirmation_message}")
            choice = input("Confirm? (yes/no): ").strip().lower()
            if choice in ("yes", "y"):
                req.confirm()
            else:
                req.reject()

        # Handle router route selections
        for req in run_output.steps_requiring_route:
            print(f"\n[HITL] {req.step_name}: {req.user_input_message}")
            if req.available_choices:
                for i, choice in enumerate(req.available_choices, 1):
                    print(f"  {i}. {choice}")
                selections = input("Select (comma-separated numbers): ").strip()
                chosen = [s.strip() for s in selections.split(",") if s.strip()]
                if len(chosen) > 1:
                    req.select_multiple(chosen)
                else:
                    req.select(chosen[0])

        run_output = loaded.continue_run(run_output)

    print(f"\nStatus: {run_output.status}")
    print(f"Output:\n{run_output.content}")


if __name__ == "__main__":
    print("HITL Config Round-Trip: Condition, Loop, Router")

    # Save and verify all three workflows
    loaded_workflows = {}
    for name, (wf, wf_id) in WORKFLOWS.items():
        loaded = save_and_verify(name, wf, wf_id)
        if loaded:
            loaded_workflows[name] = loaded

    # Let user choose which to run
    print("\n" + "=" * 60)
    print("Which workflow would you like to run?")
    print("  1. Condition (user decides branch)")
    print("  2. Loop (user confirms before starting)")
    print("  3. Router (user selects routes)")
    print("  4. Skip running")

    choice = input("\nEnter choice (1-4): ").strip()

    if choice == "1" and "condition" in loaded_workflows:
        run_workflow(loaded_workflows["condition"], "Q4 sales performance")
    elif choice == "2" and "loop" in loaded_workflows:
        run_workflow(loaded_workflows["loop"], "Optimize marketing strategy")
    elif choice == "3" and "router" in loaded_workflows:
        run_workflow(loaded_workflows["router"], "Market expansion analysis")
    elif choice == "4":
        print("Done.")
    else:
        print("Invalid choice or workflow not loaded.")
