from typing import List

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai.chat import OpenAIChat
from agno.run import RunContext
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow


# Define tools to manage a task list in workflow session state
def add_task(run_context: RunContext, task: str, priority: str = "medium") -> str:
    """Add a task to the task list in workflow session state.

    Args:
        task (str): The task to add to the list
        priority (str): Priority level (low, medium, high)
    """
    if run_context.session_state is None:
        run_context.session_state = {}

    if "task_list" not in run_context.session_state:
        run_context.session_state["task_list"] = []

    # Check if task already exists (case-insensitive)
    existing_tasks = [
        existing_task["name"].lower()
        for existing_task in run_context.session_state["task_list"]
    ]
    if task.lower() not in existing_tasks:
        task_item = {
            "name": task,
            "priority": priority,
            "status": "pending",
            "id": len(run_context.session_state["task_list"]) + 1,
        }
        run_context.session_state["task_list"].append(task_item)
        return f"Added task '{task}' with {priority} priority to the task list."
    else:
        return f"Task '{task}' already exists in the task list."


def complete_task(run_context: RunContext, task_name: str) -> str:
    """Mark a task as completed in workflow session state.

    Args:
        task_name (str): The name of the task to mark as completed
    """
    if run_context.session_state is None:
        run_context.session_state = {}

    if "task_list" not in run_context.session_state:
        run_context.session_state["task_list"] = []
        return f"Task list is empty. Cannot complete '{task_name}'."

    # Find and complete task (case-insensitive)
    for task in run_context.session_state["task_list"]:
        if task["name"].lower() == task_name.lower():
            task["status"] = "completed"
            return f"Marked task '{task['name']}' as completed."

    return f"Task '{task_name}' not found in the task list."


def set_task_priority(run_context: RunContext, task_name: str, priority: str) -> str:
    """Update the priority of a task in workflow session state.

    Args:
        task_name (str): The name of the task to update
        priority (str): New priority level (low, medium, high)
    """
    if run_context.session_state is None:
        run_context.session_state = {}

    if "task_list" not in run_context.session_state:
        run_context.session_state["task_list"] = []
        return f"Task list is empty. Cannot update priority for '{task_name}'."

    valid_priorities = ["low", "medium", "high"]
    if priority.lower() not in valid_priorities:
        return f"Invalid priority '{priority}'. Must be one of: {', '.join(valid_priorities)}"

    # Find and update task priority (case-insensitive)
    for task in run_context.session_state["task_list"]:
        if task["name"].lower() == task_name.lower():
            old_priority = task["priority"]
            task["priority"] = priority.lower()
            return f"Updated task '{task['name']}' priority from {old_priority} to {priority}."

    return f"Task '{task_name}' not found in the task list."


def list_tasks(run_context: RunContext, status_filter: str = "all") -> str:
    """List tasks from workflow session state with optional status filtering.

    Args:
        status_filter (str): Filter by status - 'all', 'pending', 'completed'
    """
    if run_context.session_state is None:
        run_context.session_state = {}

    if (
        "task_list" not in run_context.session_state
        or not run_context.session_state["task_list"]
    ):
        return "Task list is empty."

    tasks = run_context.session_state["task_list"]

    if status_filter != "all":
        tasks = [task for task in tasks if task["status"] == status_filter]
        if not tasks:
            return f"No {status_filter} tasks found."

    # Sort by priority (high -> medium -> low) and then by id
    priority_order = {"high": 1, "medium": 2, "low": 3}
    tasks = sorted(tasks, key=lambda x: (priority_order.get(x["priority"], 3), x["id"]))

    tasks_str = "\n".join(
        [
            f"- [{task['status'].upper()}] {task['name']} (Priority: {task['priority']})"
            for task in tasks
        ]
    )
    return f"Task list ({status_filter}):\n{tasks_str}"


def clear_completed_tasks(run_context: RunContext) -> str:
    """Remove all completed tasks from the task list."""
    if run_context.session_state is None:
        run_context.session_state = {}

    if "task_list" not in run_context.session_state:
        run_context.session_state["task_list"] = []
        return "Task list is empty."

    original_count = len(run_context.session_state["task_list"])
    run_context.session_state["task_list"] = [
        task
        for task in run_context.session_state["task_list"]
        if task["status"] != "completed"
    ]
    completed_count = original_count - len(run_context.session_state["task_list"])

    return f"Removed {completed_count} completed tasks from the list."


# Create specialized agents with different tool sets
task_manager = Agent(
    name="Task Manager",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[add_task, complete_task, set_task_priority],
    instructions=[
        "You are a task management specialist.",
        "You can add new tasks, mark tasks as completed, and update task priorities.",
        "Always use the provided tools to interact with the task list.",
        "When adding tasks, consider setting appropriate priorities based on urgency and importance.",
        "Be efficient and clear in your responses.",
    ],
)

task_viewer = Agent(
    name="Task Viewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[list_tasks],
    instructions=[
        "You are a task viewing specialist.",
        "You can display tasks with various filters (all, pending, completed).",
        "Present task information in a clear, organized format.",
        "Help users understand their task status and priorities.",
    ],
)

task_organizer = Agent(
    name="Task Organizer",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[list_tasks, clear_completed_tasks, set_task_priority],
    instructions=[
        "You are a task organization specialist.",
        "You can view tasks, clean up completed tasks, and reorganize priorities.",
        "Focus on helping users maintain an organized and efficient task list.",
        "Suggest improvements to task organization when appropriate.",
    ],
)

# Create steps for each agent
manage_tasks_step = Step(
    name="manage_tasks",
    description="Add new tasks, complete tasks, or update priorities",
    agent=task_manager,
)

view_tasks_step = Step(
    name="view_tasks",
    description="View and display task lists with filtering",
    agent=task_viewer,
)

organize_tasks_step = Step(
    name="organize_tasks",
    description="Organize tasks, clean up completed items, adjust priorities",
    agent=task_organizer,
)


def task_router(step_input: StepInput) -> List[Step]:
    """
    Route to the appropriate task management agent based on the input.
    Returns a list containing the step to execute.
    """
    # Use the original workflow input if this is the first step
    message = step_input.previous_step_content or step_input.input or ""
    message_lower = str(message).lower()

    # Keywords for different types of task operations
    management_keywords = [
        "add",
        "create",
        "new task",
        "complete",
        "finish",
        "done",
        "mark as",
        "priority",
        "urgent",
        "important",
        "update",
    ]

    viewing_keywords = [
        "show",
        "list",
        "display",
        "view",
        "see",
        "what tasks",
        "current",
        "pending",
        "completed",
        "status",
    ]

    organizing_keywords = [
        "clean",
        "organize",
        "clear",
        "remove completed",
        "reorganize",
        "cleanup",
        "tidy",
        "sort",
        "arrange",
    ]

    # Check for organizing operations first (most specific)
    if any(keyword in message_lower for keyword in organizing_keywords):
        print("🗂️ Organization request detected: Using Task Organizer")
        return [organize_tasks_step]

    # Check for management operations
    elif any(keyword in message_lower for keyword in management_keywords):
        print("⚙️ Management request detected: Using Task Manager")
        return [manage_tasks_step]

    # Check for viewing operations
    elif any(keyword in message_lower for keyword in viewing_keywords):
        print("👀 Viewing request detected: Using Task Viewer")
        return [view_tasks_step]

    # Default to management for ambiguous requests
    else:
        print("🤔 Ambiguous request: Defaulting to Task Manager")
        return [manage_tasks_step]


# Create workflow with Router and shared session state
task_workflow = Workflow(
    name="Smart Task Management Workflow",
    description="Intelligently routes task management requests to specialized agents",
    steps=[
        Router(
            name="task_management_router",
            selector=task_router,
            choices=[manage_tasks_step, view_tasks_step, organize_tasks_step],
            description="Routes requests to the most appropriate task management agent",
        )
    ],
    session_state={"task_list": []},  # Initialize empty task list
    db=SqliteDb(db_file="tmp/workflow.db"),
)

if __name__ == "__main__":
    # Example 1: Add some tasks (should route to Task Manager)
    print("=== Example 1: Adding Tasks ===")
    task_workflow.print_response(
        input="Add these tasks: 'Review project proposal' with high priority, 'Buy groceries' with low priority, and 'Call dentist' with medium priority."
    )
    print("Workflow session state:", task_workflow.get_session_state())

    # Example 2: View tasks (should route to Task Viewer)
    print("\n=== Example 2: Viewing Tasks ===")
    task_workflow.print_response(input="Show me all my current tasks")

    print("Workflow session state:", task_workflow.get_session_state())

    # Example 3: Complete a task (should route to Task Manager)
    print("\n=== Example 3: Completing Tasks ===")
    task_workflow.print_response(input="Mark 'Buy groceries' as completed")

    print("Workflow session state:", task_workflow.get_session_state())

    # Example 4: Organize and clean up (should route to Task Organizer)
    print("\n=== Example 4: Organizing Tasks ===")
    task_workflow.print_response(
        input="Clean up my completed tasks and show me what's left"
    )

    print("Workflow session state:", task_workflow.get_session_state())

    # Example 5: View only pending tasks (should route to Task Viewer)
    print("\n=== Example 5: Filtered View ===")
    task_workflow.print_response(input="Show me only my pending tasks")

    print("\nFinal workflow session state:", task_workflow.get_session_state())
