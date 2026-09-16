"""Runnable companion to the task agent guide."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.run import RunContext

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

# Demo product records. Changes last until this process restarts.
tasks = {
    "task-1": {"owner": "alice", "title": "Review release notes", "done": False},
    "task-2": {"owner": "bob", "title": "Update billing settings", "done": False},
}


def list_tasks(run_context: RunContext) -> list[dict]:
    """List tasks belonging to the current user."""
    return [
        {"id": task_id, "title": task["title"], "done": task["done"]}
        for task_id, task in tasks.items()
        if task["owner"] == run_context.user_id
    ]


def complete_task(run_context: RunContext, task_id: str) -> str:
    """Mark one of the current user's tasks complete."""
    task = tasks.get(task_id)
    if task is None or task["owner"] != run_context.user_id:
        return "Task not found."
    task["done"] = True
    return f"Completed: {task['title']}"


agent = Agent(
    id="task-agent",
    model=OpenAIResponses(id="gpt-5.6"),
    db=SqliteDb(db_file="task-agent.db"),
    add_history_to_context=True,
    tools=[list_tasks, complete_task],
    instructions=[
        "Help the user manage their tasks.",
        "Use the tools to read current tasks and make changes.",
        "Only complete a task when the user asks you to.",
        "Report a change as complete only after the tool confirms it.",
    ],
)

agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="task_agent:app", host="127.0.0.1", port=7777)
