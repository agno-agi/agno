"""
State In Router
===============

Demonstrates router selectors that use and update workflow session state for adaptive routing.
"""

from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.models.openai.chat import OpenAIChat as OpenAIChatLegacy
from agno.run import RunContext
from agno.workflow.router import Router
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ---------------------------------------------------------------------------
# Define Router Functions (Preference-Based Routing)
# ---------------------------------------------------------------------------
def route_based_on_user_preference(step_input: StepInput, session_state: dict) -> Step:
    print("\n=== Routing Decision ===")
    print(f"User ID: {session_state.get('current_user_id')}")
    print(f"Session ID: {session_state.get('current_session_id')}")

    user_preference = session_state.get("agent_preference", "general")
    interaction_count = session_state.get("interaction_count", 0)

    print(f"User Preference: {user_preference}")
    print(f"Interaction Count: {interaction_count}")

    session_state["interaction_count"] = interaction_count + 1

    if user_preference == "technical":
        print("Routing to Technical Expert")
        return technical_step
    if user_preference == "friendly":
        print("Routing to Friendly Assistant")
        return friendly_step

    if interaction_count == 0:
        print("Routing to Onboarding (first interaction)")
        return onboarding_step

    print("Routing to General Assistant")
    return general_step


def set_user_preference(step_input: StepInput, session_state: dict) -> StepOutput:
    print("\n=== Setting User Preference ===")
    interaction_count = session_state.get("interaction_count", 0)

    if interaction_count % 3 == 1:
        session_state["agent_preference"] = "technical"
        preference = "technical"
    elif interaction_count % 3 == 2:
        session_state["agent_preference"] = "friendly"
        preference = "friendly"
    else:
        session_state["agent_preference"] = "general"
        preference = "general"

    print(f"Set preference to: {preference}")
    return StepOutput(content=f"Preference set to: {preference}")


# ---------------------------------------------------------------------------
# Create Agents (Preference-Based Routing)
# ---------------------------------------------------------------------------
onboarding_agent = Agent(
    name="Onboarding Agent",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=(
        "Welcome new users and ask about their preferences. "
        "Determine if they prefer technical or friendly assistance."
    ),
    markdown=True,
)

technical_agent = Agent(
    name="Technical Expert",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=(
        "You are a technical expert. Provide detailed, technical answers with code examples and best practices."
    ),
    markdown=True,
)

friendly_agent = Agent(
    name="Friendly Assistant",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=(
        "You are a friendly, casual assistant. Use simple language and make the conversation engaging."
    ),
    markdown=True,
)

general_agent = Agent(
    name="General Assistant",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=(
        "You are a balanced assistant. Provide helpful answers that are neither too technical nor too casual."
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Define Steps (Preference-Based Routing)
# ---------------------------------------------------------------------------
onboarding_step = Step(
    name="Onboard User",
    description="Onboard new user and set preferences",
    agent=onboarding_agent,
)

technical_step = Step(
    name="Technical Response",
    description="Provide technical assistance",
    agent=technical_agent,
)

friendly_step = Step(
    name="Friendly Response",
    description="Provide friendly assistance",
    agent=friendly_agent,
)

general_step = Step(
    name="General Response",
    description="Provide general assistance",
    agent=general_agent,
)

# ---------------------------------------------------------------------------
# Create Workflow (Preference-Based Routing)
# ---------------------------------------------------------------------------
adaptive_assistant_workflow = Workflow(
    name="Adaptive Assistant Workflow",
    steps=[
        Router(
            name="Route to Appropriate Agent",
            description="Route to the appropriate agent based on user preferences",
            selector=route_based_on_user_preference,
            choices=[
                onboarding_step,
                technical_step,
                friendly_step,
                general_step,
            ],
        ),
        Step(
            name="Update Preferences",
            description="Update user preferences based on interaction",
            executor=set_user_preference,
        ),
    ],
    session_state={
        "agent_preference": "general",
        "interaction_count": 0,
    },
)


# ---------------------------------------------------------------------------
# Define Task Tools (Task Routing)
# ---------------------------------------------------------------------------
def add_task(run_context: RunContext, task: str, priority: str = "medium") -> str:
    if run_context.session_state is None:
        run_context.session_state = {}

    if "task_list" not in run_context.session_state:
        run_context.session_state["task_list"] = []

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

    return f"Task '{task}' already exists in the task list."


def complete_task(run_context: RunContext, task_name: str) -> str:
    if run_context.session_state is None:
        run_context.session_state = {}

    if "task_list" not in run_context.session_state:
        run_context.session_state["task_list"] = []
        return f"Task list is empty. Cannot complete '{task_name}'."

    for task in run_context.session_state["task_list"]:
        if task["name"].lower() == task_name.lower():
            task["status"] = "completed"
            return f"Marked task '{task['name']}' as completed."

    return f"Task '{task_name}' not found in the task list."


def set_task_priority(run_context: RunContext, task_name: str, priority: str) -> str:
    if run_context.session_state is None:
        run_context.session_state = {}

    if "task_list" not in run_context.session_state:
        run_context.session_state["task_list"] = []
        return f"Task list is empty. Cannot update priority for '{task_name}'."

    valid_priorities = ["low", "medium", "high"]
    if priority.lower() not in valid_priorities:
        return f"Invalid priority '{priority}'. Must be one of: {', '.join(valid_priorities)}"

    for task in run_context.session_state["task_list"]:
        if task["name"].lower() == task_name.lower():
            old_priority = task["priority"]
            task["priority"] = priority.lower()
            return f"Updated task '{task['name']}' priority from {old_priority} to {priority}."

    return f"Task '{task_name}' not found in the task list."


def list_tasks(run_context: RunContext, status_filter: str = "all") -> str:
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


# ---------------------------------------------------------------------------
# Create Agents (Task Routing)
# ---------------------------------------------------------------------------
task_manager = Agent(
    name="Task Manager",
    model=OpenAIChatLegacy(id="gpt-5.2"),
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
    model=OpenAIChatLegacy(id="gpt-5.2"),
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
    model=OpenAIChatLegacy(id="gpt-5.2"),
    tools=[list_tasks, clear_completed_tasks, set_task_priority],
    instructions=[
        "You are a task organization specialist.",
        "You can view tasks, clean up completed tasks, and reorganize priorities.",
        "Focus on helping users maintain an organized and efficient task list.",
        "Suggest improvements to task organization when appropriate.",
    ],
)

# ---------------------------------------------------------------------------
# Define Steps (Task Routing)
# ---------------------------------------------------------------------------
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
    message = step_input.previous_step_content or step_input.input or ""
    message_lower = str(message).lower()

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

    if any(keyword in message_lower for keyword in organizing_keywords):
        print("[INFO] Organization request detected: Using Task Organizer")
        return [organize_tasks_step]
    if any(keyword in message_lower for keyword in management_keywords):
        print("[INFO] Management request detected: Using Task Manager")
        return [manage_tasks_step]
    if any(keyword in message_lower for keyword in viewing_keywords):
        print("[INFO] Viewing request detected: Using Task Viewer")
        return [view_tasks_step]

    print("[INFO] Ambiguous request: Defaulting to Task Manager")
    return [manage_tasks_step]


# ---------------------------------------------------------------------------
# Create Workflow (Task Routing)
# ---------------------------------------------------------------------------
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
    session_state={"task_list": []},
    db=SqliteDb(db_file="tmp/workflow.db"),
)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
def run_adaptive_assistant_example() -> None:
    queries = [
        "Hello! I'm new here.",
        "How do I implement a binary search tree in Python?",
        "What's the best pizza topping?",
        "Explain quantum computing",
    ]

    for i, query in enumerate(queries, 1):
        print("\n" + "=" * 80)
        print(f"Interaction {i}: {query}")
        print("=" * 80)

        adaptive_assistant_workflow.print_response(
            input=query,
            session_id="user-456",
            user_id="user-456",
            stream=True,
        )


def run_task_workflow_example() -> None:
    print("=== Example 1: Adding Tasks ===")
    task_workflow.print_response(
        input="Add these tasks: 'Review project proposal' with high priority, 'Buy groceries' with low priority, and 'Call dentist' with medium priority."
    )
    print("Workflow session state:", task_workflow.get_session_state())

    print("\n=== Example 2: Viewing Tasks ===")
    task_workflow.print_response(input="Show me all my current tasks")
    print("Workflow session state:", task_workflow.get_session_state())

    print("\n=== Example 3: Completing Tasks ===")
    task_workflow.print_response(input="Mark 'Buy groceries' as completed")
    print("Workflow session state:", task_workflow.get_session_state())

    print("\n=== Example 4: Organizing Tasks ===")
    task_workflow.print_response(
        input="Clean up my completed tasks and show me what's left"
    )
    print("Workflow session state:", task_workflow.get_session_state())

    print("\n=== Example 5: Filtered View ===")
    task_workflow.print_response(input="Show me only my pending tasks")
    print("\nFinal workflow session state:", task_workflow.get_session_state())


if __name__ == "__main__":
    run_adaptive_assistant_example()
    run_task_workflow_example()
