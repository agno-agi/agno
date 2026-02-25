"""
Task Mode Streaming Example - Real-time Task List Demo
=======================================================

This example demonstrates how to show a REAL-TIME task list that:
1. Shows tasks as they are created (via create_task tool)
2. Updates task status as they are executed (via execute_task tool)
3. Ticks off tasks as they complete

The frontend can use ToolCallCompletedEvent to track:
- create_task: Add a new task to the list
- execute_task: Mark task as in_progress, then completed
- update_task_status: Update task status
"""

from typing import Dict
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.team.mode import TeamMode
from agno.run.team import (
    TaskStateUpdatedEvent,
    TaskIterationStartedEvent,
    ToolCallStartedEvent,
    ToolCallCompletedEvent,
)


# Simulated frontend task list state
class TaskListUI:
    """Simulates a frontend task list component that updates in real-time."""

    def __init__(self):
        self.tasks: Dict[str, dict] = {}  # task_id -> task_data

    def render(self):
        """Render the current task list state."""
        if not self.tasks:
            print("  (No tasks yet)")
            return

        for task_id, task in self.tasks.items():
            status_icons = {
                "pending": "[ ]",
                "in_progress": "[~]",
                "completed": "[x]",
                "failed": "[!]",
                "blocked": "[-]",
            }
            icon = status_icons.get(task.get("status", "pending"), "[ ]")
            title = task.get("title", "Untitled")
            assignee = task.get("assignee", "")
            assignee_str = f" ({assignee})" if assignee else ""
            print(f"  {icon} {title}{assignee_str}")

    def add_task(self, task_id: str, title: str, assignee: str = None):
        """Add a new task to the list."""
        self.tasks[task_id] = {
            "title": title,
            "assignee": assignee,
            "status": "pending",
        }

    def update_status(self, task_id: str, status: str, result: str = None):
        """Update a task's status."""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
            if result:
                self.tasks[task_id]["result"] = result


def main():
    # Create member agents
    researcher = Agent(
        name="Researcher",
        role="Research specialist",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You research topics and provide information.",
    )

    writer = Agent(
        name="Writer",
        role="Content writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You write content based on research.",
    )

    # Create team in tasks mode
    team = Team(
        name="Content Team",
        mode=TeamMode.tasks,
        model=OpenAIChat(id="gpt-4o"),
        members=[researcher, writer],
        instructions=[
            "You are a content creation team leader.",
            "IMPORTANT: Break down the user's request into MULTIPLE separate tasks.",
            "Create at least 3-4 distinct tasks for complex requests.",
            "Assign tasks to the appropriate team member.",
            "Execute tasks one by one and track progress.",
        ],
        max_iterations=5,
    )

    print("=" * 60)
    print("REAL-TIME TASK LIST - Watch tasks appear and complete!")
    print("=" * 60)
    print()

    # Frontend task list state
    task_ui = TaskListUI()

    # A more complex request that should generate multiple tasks
    request = """Create a mini blog post about "The Future of AI in Healthcare" with:
1. Research the current state of AI in healthcare
2. Research future predictions and trends  
3. Write an introduction paragraph
4. Write a main body paragraph
5. Write a conclusion paragraph"""

    # Run with streaming events
    for event in team.run(
        request,
        stream=True,
        stream_events=True,
    ):
        # Track task creation via create_task tool
        if isinstance(event, ToolCallCompletedEvent):
            tool_name = event.tool.tool_name if event.tool else None
            tool_args = event.tool.tool_args if event.tool else {}

            if tool_name == "create_task":
                # Parse the result to get the task ID
                result = event.tool.result if event.tool else ""
                task_id = None
                if result and "Task created:" in result:
                    # Extract task ID from result like "Task created: [abc123] Title"
                    try:
                        task_id = result.split("[")[1].split("]")[0]
                    except (IndexError, AttributeError):
                        pass

                title = tool_args.get("title", "Unknown task")
                assignee = tool_args.get("assignee", "")

                if task_id:
                    task_ui.add_task(task_id, title, assignee)
                    print(f"\n+ Task created: {title}")
                    print("-" * 40)
                    task_ui.render()
                    print("-" * 40)

            elif tool_name == "execute_task":
                task_id = tool_args.get("task_id", "")
                if task_id and task_id in task_ui.tasks:
                    # Task completed
                    result = event.tool.result if event.tool else ""
                    task_ui.update_status(task_id, "completed", result)
                    print(f"\n* Task completed: {task_ui.tasks[task_id]['title']}")
                    print("-" * 40)
                    task_ui.render()
                    print("-" * 40)

            elif tool_name == "execute_tasks_parallel":
                # Multiple tasks completed
                task_ids = tool_args.get("task_ids", [])
                for tid in task_ids:
                    if tid in task_ui.tasks:
                        task_ui.update_status(tid, "completed")
                if task_ids:
                    print("\n* Tasks completed in parallel")
                    print("-" * 40)
                    task_ui.render()
                    print("-" * 40)

        # Show when task execution starts
        elif isinstance(event, ToolCallStartedEvent):
            tool_name = event.tool.tool_name if event.tool else None
            tool_args = event.tool.tool_args if event.tool else {}

            if tool_name == "execute_task":
                task_id = tool_args.get("task_id", "")
                if task_id and task_id in task_ui.tasks:
                    task_ui.update_status(task_id, "in_progress")
                    print(f"\n~ Executing: {task_ui.tasks[task_id]['title']}...")

        # Handle iteration events
        elif isinstance(event, TaskIterationStartedEvent):
            print(f"\n>>> Iteration {event.iteration}/{event.max_iterations}")

        # Final state from TaskStateUpdatedEvent
        elif isinstance(event, TaskStateUpdatedEvent):
            if event.goal_complete:
                print("\n" + "=" * 60)
                print("GOAL COMPLETE!")
                print("=" * 60)
                if event.completion_summary:
                    print(f"Summary: {event.completion_summary[:200]}...")
                print()
                print("Final task list:")
                print("-" * 40)
                for task in event.tasks:
                    status_icons = {
                        "pending": "[ ]",
                        "in_progress": "[~]",
                        "completed": "[x]",
                        "failed": "[!]",
                        "blocked": "[-]",
                    }
                    icon = status_icons.get(task.status, "[ ]")
                    assignee_str = f" ({task.assignee})" if task.assignee else ""
                    print(f"  {icon} {task.title}{assignee_str}")
                print("-" * 40)

    print()
    print("=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
