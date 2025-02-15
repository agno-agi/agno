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
from agno.models.openai import OpenAIChat
from agno.tools.todoist import TodoistTools

todoist_agent = Agent(
    name="Todoist Agent",
    role="Manage your todoist tasks",
    instructions=[
        "When given a task, create a todoist task for it.",
        "When given a list of tasks, create a todoist task for each one.",
        "When given a task to update, update the todoist task.",
        "When given a task to delete, delete the todoist task.",
        "When given a task to get, get the todoist task.",
    ],
    agent_id="todoist-agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[TodoistTools()],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
)

# Example 1: Create a task
print("\n=== Create a task ===")
todoist_agent.print_response("Create a todoist task to buy groceries tomorrow at 10am")


# Example 2: Delete a task
print("\n=== Delete a task ===")
todoist_agent.print_response(
    "Delete the todoist task to buy groceries tomorrow at 10am"
)


# Example 3: Get all tasks
print("\n=== Get all tasks ===")
todoist_agent.print_response("Get all the todoist tasks")
