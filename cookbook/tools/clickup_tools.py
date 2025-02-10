"""
Steps to Get Your ClickUp API Key

Step 1: Log In to ClickUp
Step 2: Navigate to Settings (usually a circle with your initials) click on it
Step 3: Access the Apps Section: In the settings sidebar on the left, scroll down until you find Apps. Click on it to access the API settings.
Step 4: Generate Your API Key
In the Apps section, you should see an option labeled API Token. If it’s not already generated, look for a button that says Generate and click it.
Once generated, your API key will be displayed. Make sure to copy this key and store it as CLICKUP_API_KEY in .env file to use it.

Steps To find your MASTER_SPACE_ID :
clickup space url structure: https://app.clickup.com/{MASTER_SPACE_ID}/v/o/s/{SPACE_ID}
1. copy any space url from your clickup workspace all follow above url structure.
2. To use clickup tool copy the MASTER_SPACE_ID and store it .env file.

"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.clickup_tool import ClickUpTools

clickup_agent = Agent(
    name="ClickUp Agent",
    role="Manage ClickUp tasks and spaces",
    model=OpenAIChat(model="gpt-4o-mini"),
    tools=[ClickUpTools(list_spaces=True, list_lists=True, list_tasks=True)],
    instructions=[
        "You are a ClickUp assistant that helps users manage their tasks and spaces.",
        "You can:",
        "1. List all available spaces",
        "2. List tasks from a specific space",
        "3. List all lists in a space",
        "4. Create new tasks with title, description, and status",
        "When creating tasks:",
        "- Always get space name, task name, and description",
        "- Status can be: todo, in progress, or done",
        "- If status is not specified, use 'todo' as default",
        "Be helpful and guide users if they need more information.",
    ],
    show_tool_calls=True,
    markdown=True,
)

clickup_agent.print_response(
    "List all spaces i have",
    markdown=True,
)
clickup_agent.print_response(
    "Create a task (status 'To Do') called 'QA task' in Project 1 in the Team Space. The description should be about running basic QA checks on our Python codebase.",
    markdown=True,
)
