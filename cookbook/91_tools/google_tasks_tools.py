"""Google Tasks toolkit — manage Google Tasks task lists and tasks from an agent.

Setup steps (first-time only):

1. Enable the Google Tasks API for your project:
   https://console.cloud.google.com/apis/enableflow?apiid=tasks.googleapis.com

2. Create OAuth 2.0 credentials (Desktop app) from
   API & Services -> Credentials and download the JSON file.

3. In the OAuth consent screen, add the Google Tasks scopes:
   - https://www.googleapis.com/auth/tasks.readonly  (read-only)
   - https://www.googleapis.com/auth/tasks            (full access, required for writes)

4. Add yourself as a test user while the app is in "Testing" mode.

5. Pass the downloaded JSON file to the toolkit via ``credentials_path``, or leave
   it as ``credentials.json`` next to this script.

On first run, a browser window will open for consent and a ``token.json`` file
will be written next to this script for reuse on subsequent runs.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.tasks import GoogleTasksTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GoogleTasksTools(
            # credentials_path="credentials.json",
            # token_path="token.json",
            oauth_port=8080,
        )
    ],
    instructions=[
        "You are a task management assistant backed by Google Tasks.",
        "Always discover available task lists with list_task_lists before creating tasks.",
        "When the user asks to add a task, confirm the target task list if more than one exists.",
        "Use RFC 3339 timestamps for due dates (e.g. 2026-12-31T00:00:00Z).",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    # Example 1 — list all task lists
    agent.print_response("Show me all my Google task lists.", stream=True)

    # Example 2 — create a task list and add a task to it
    # agent.print_response(
    #     "Create a new task list called 'Side Project' and add a task "
    #     "titled 'Draft launch plan' due next Friday.",
    #     stream=True,
    # )

    # Example 3 — list pending work in a specific list
    # agent.print_response(
    #     "What tasks are in my 'Work' list that haven't been completed yet?",
    #     stream=True,
    # )

    # Example 4 — mark a task complete
    # agent.print_response(
    #     "Mark the 'Draft launch plan' task as complete.",
    #     stream=True,
    # )

    # Example 5 — add a subtask
    # agent.print_response(
    #     "Under the 'Draft launch plan' task, add a subtask called 'Write intro paragraph'.",
    #     stream=True,
    # )
