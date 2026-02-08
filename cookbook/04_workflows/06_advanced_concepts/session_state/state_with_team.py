"""
State With Team
===============

Demonstrates shared session state across team and agent steps for project-step lifecycle management.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai.chat import OpenAIChat
from agno.run import RunContext
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/workflow.db")


# ---------------------------------------------------------------------------
# Define Team Tools
# ---------------------------------------------------------------------------
def add_step(
    run_context: RunContext,
    step_name: str,
    assignee: str,
    priority: str = "medium",
) -> str:
    if run_context.session_state is None:
        run_context.session_state = {}

    if "steps" not in run_context.session_state:
        run_context.session_state["steps"] = []

    step = {
        "name": step_name,
        "assignee": assignee,
        "status": "pending",
        "priority": priority,
        "created_at": "now",
    }
    run_context.session_state["steps"].append(step)

    return f"[OK] Successfully added step '{step_name}' assigned to {assignee} (priority: {priority}). Total steps: {len(run_context.session_state['steps'])}"


def delete_step(run_context: RunContext, step_name: str) -> str:
    if run_context.session_state is None or "steps" not in run_context.session_state:
        return "[ERROR] No steps found to delete"

    steps = run_context.session_state["steps"]
    for i, step in enumerate(steps):
        if step["name"] == step_name:
            deleted_step = steps.pop(i)
            return f"[OK] Successfully deleted step '{step_name}' (was assigned to {deleted_step['assignee']}). Remaining steps: {len(steps)}"

    return f"[ERROR] Step '{step_name}' not found in the list"


# ---------------------------------------------------------------------------
# Define Agent Tools
# ---------------------------------------------------------------------------
def update_step_status(
    run_context: RunContext,
    step_name: str,
    new_status: str,
    notes: str = "",
) -> str:
    if run_context.session_state is None or "steps" not in run_context.session_state:
        return "[ERROR] No steps found in workflow session state"

    steps = run_context.session_state["steps"]
    for step in steps:
        if step["name"] == step_name:
            old_status = step["status"]
            step["status"] = new_status
            if notes:
                step["notes"] = notes
            step["last_updated"] = "now"

            result = f"[OK] Updated step '{step_name}' status from '{old_status}' to '{new_status}'"
            if notes:
                result += f" with notes: {notes}"
            return result

    return f"[ERROR] Step '{step_name}' not found in the list"


def assign_step(run_context: RunContext, step_name: str, new_assignee: str) -> str:
    if run_context.session_state is None or "steps" not in run_context.session_state:
        return "[ERROR] No steps found in workflow session state"

    steps = run_context.session_state["steps"]
    for step in steps:
        if step["name"] == step_name:
            old_assignee = step["assignee"]
            step["assignee"] = new_assignee
            step["last_updated"] = "now"
            return f"[OK] Reassigned step '{step_name}' from {old_assignee} to {new_assignee}"

    return f"[ERROR] Step '{step_name}' not found in the list"


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
step_manager = Agent(
    name="StepManager",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=[
        "You are a precise step manager. Your ONLY job is to use the provided tools.",
        "When asked to add a step: ALWAYS use add_step(step_name, assignee, priority).",
        "When asked to delete a step: ALWAYS use delete_step(step_name).",
        "Do NOT create imaginary steps or lists.",
        "Do NOT provide explanations beyond what the tool returns.",
        "Be direct and use the tools immediately.",
    ],
)

step_coordinator = Agent(
    name="StepCoordinator",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=[
        "You coordinate with the StepManager to ensure tasks are completed.",
        "Support the team by confirming actions and helping with coordination.",
        "Be concise and focus on the specific request.",
    ],
)

status_manager = Agent(
    name="StatusManager",
    model=OpenAIChat(id="gpt-5.2"),
    tools=[update_step_status, assign_step],
    instructions=[
        "You manage step statuses and assignments using the provided tools.",
        "Use update_step_status(step_name, new_status, notes) to change step status.",
        "Use assign_step(step_name, new_assignee) to reassign steps.",
        "Valid statuses: 'pending', 'in_progress', 'completed', 'blocked', 'cancelled'.",
        "Be precise and only use the tools provided.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
management_team = Team(
    name="ManagementTeam",
    members=[step_manager, step_coordinator],
    tools=[add_step, delete_step],
    instructions=[
        "You are a step management team that ONLY uses the provided tools for adding and deleting steps.",
        "CRITICAL: Use add_step(step_name, assignee, priority) to add steps.",
        "CRITICAL: Use delete_step(step_name) to delete steps.",
        "IMPORTANT: You do NOT handle status updates - that's handled by the status manager in the next step.",
        "IMPORTANT: Do NOT delete steps when asked to mark them as completed - only delete when explicitly asked to delete.",
        "If asked to mark a step as completed, respond that status updates are handled by the status manager.",
        "Do NOT create fictional content or step lists.",
        "Execute only the requested add/delete actions using tools and report the result.",
    ],
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
manage_steps_step = Step(
    name="manage_steps",
    description="Management team uses tools to add/delete steps in the workflow session state",
    team=management_team,
)

update_status_step = Step(
    name="update_status",
    description="Status manager updates step statuses and assignments",
    agent=status_manager,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
project_workflow = Workflow(
    name="Project Management Workflow",
    db=db,
    steps=[manage_steps_step, update_status_step],
    session_state={"steps": []},
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def print_current_steps(workflow) -> None:
    session_state = workflow.get_session_state()
    if not session_state or "steps" not in session_state:
        print("No steps in workflow")
        return

    steps = session_state["steps"]
    if not steps:
        print("Step list is empty")
        return

    print("Current Project Steps:")
    for i, step in enumerate(steps, 1):
        status_label = {
            "pending": "[PENDING]",
            "in_progress": "[IN_PROGRESS]",
            "completed": "[COMPLETED]",
            "blocked": "[BLOCKED]",
            "cancelled": "[CANCELLED]",
        }.get(step["status"], "[UNKNOWN]")

        priority_label = {"high": "[HIGH]", "medium": "[MEDIUM]", "low": "[LOW]"}.get(
            step.get("priority", "medium"),
            "[MEDIUM]",
        )

        print(
            f"  {i}. {status_label} {priority_label} {step['name']} (assigned to: {step['assignee']}, status: {step['status']})"
        )
        if "notes" in step:
            print(f"     Notes: {step['notes']}")
    print()


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Starting Project Management Workflow Tests")

    print("=" * 60)
    print("Example 1: Add Multiple Steps")
    print("=" * 60)
    project_workflow.print_response(
        input="Add a high priority step called 'Setup Database' assigned to Alice, and a medium priority step called 'Create API' assigned to Bob"
    )
    print_current_steps(project_workflow)
    print(f"Workflow Session State: {project_workflow.get_session_state()}")
    print()

    print("=" * 60)
    print("Example 2: Update Step Status")
    print("=" * 60)
    project_workflow.print_response(
        input="Mark 'Setup Database' as in_progress with notes 'Started database schema design'"
    )
    print_current_steps(project_workflow)
    print(f"Workflow Session State: {project_workflow.get_session_state()}")
    print()

    print("=" * 60)
    print("Example 3: Reassign and Complete Step")
    print("=" * 60)
    project_workflow.print_response(
        input="Reassign 'Create API' to Charlie, then mark it as completed with notes 'API endpoints implemented and tested'"
    )
    print_current_steps(project_workflow)
    print(f"Workflow Session State: {project_workflow.get_session_state()}")
    print()

    print("=" * 60)
    print("Example 4: Add and Manage More Steps")
    print("=" * 60)
    project_workflow.print_response(
        input="Add a low priority step 'Write Tests' assigned to Dave, then mark 'Setup Database' as completed"
    )
    print_current_steps(project_workflow)
    print(f"Workflow Session State: {project_workflow.get_session_state()}")
    print()

    print("=" * 60)
    print("Example 5: Delete Step")
    print("=" * 60)
    project_workflow.print_response(
        input="Delete the 'Write Tests' step and add a high priority 'Deploy to Production' step assigned to Eve"
    )
    print_current_steps(project_workflow)
    print(f"Workflow Session State: {project_workflow.get_session_state()}")
