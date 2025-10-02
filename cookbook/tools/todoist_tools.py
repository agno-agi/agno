"""
Example showing how to use the Todoist Tools with Agno

Requirements:
- Sign up/login to Todoist and get a Todoist API Token (get from https://app.todoist.com/app/settings/integrations/developer)
- pip install todoist-api-python

Usage:
- Set the following environment variables:
    export TODOIST_API_TOKEN="your_api_token"

- Or provide them when creating the TodoistTools instance
"""

from agno.agent import Agent
from agno.models.google.gemini import Gemini
from agno.tools.todoist import TodoistTools

# Example 1: All functions available (default behavior)
todoist_agent_all = Agent(
    name="Todoist Agent - All Functions",
    role="Manage your todoist tasks with full capabilities",
    instructions=[
        "You have access to all Todoist operations.",
        "You can create, read, update, delete tasks and manage projects.",
    ],
    id="todoist-agent-all",
    model=Gemini("gemini-2.0-flash-exp"),
    tools=[TodoistTools()],
    markdown=True,
)


# Example 3: Exclude dangerous functions
todoist_agent = Agent(
    name="Todoist Agent - Safe Mode",
    role="Manage your todoist tasks safely",
    instructions=[
        "You can create and update tasks but cannot delete anything.",
        "You have read access to all tasks and projects.",
    ],
    id="todoist-agent-safe",
    model=Gemini("gemini-2.0-flash-exp"),
    tools=[TodoistTools(exclude_tools=["delete_task"])],
    markdown=True,
)


# Example 1: Create a task
print("\n=== Create a task ===")
todoist_agent_all.print_response(
    "Create a todoist task to buy groceries tomorrow at 10am"
)


# Example 2: Delete a task
print("\n=== Delete a task ===")
todoist_agent.print_response(
    "Delete the todoist task to buy groceries tomorrow at 10am"
)
