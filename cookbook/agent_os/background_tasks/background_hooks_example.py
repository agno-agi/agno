"""
Example: Using Background Post-Hooks in AgentOS

This example demonstrates how to run post-hooks as FastAPI background tasks,
making them completely non-blocking.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run.agent import RunInput


# Define a pre-hook that runs before processing (e.g., request validation, logging)
def log_request(run_input: RunInput, agent):
    """
    This pre-hook will run in the background before the agent processes the request.
    Note: Pre-hooks in background mode cannot modify run_input.
    """
    print(f"[Background Pre-Hook] Request received for agent: {agent.name}")
    print(f"[Background Pre-Hook] Input: {run_input.input_content}")
    print("[Background Pre-Hook] Request logged!")


# Define a post-hook that might take a while (e.g., logging, analytics, notifications)
def log_analytics(run_output, agent, session):
    """
    This post-hook will run in the background after the response is sent to the user.
    It won't block the API response.
    """
    print(f"[Background Task] Logging analytics for run: {run_output.run_id}")
    print(f"[Background Task] Agent: {agent.name}")
    print(f"[Background Task] Session: {session.session_id}")
    print("[Background Task] Analytics logged successfully!")


# Another post-hook for sending notifications
def send_notification(run_output, agent):
    """
    Another background task that sends notifications without blocking the response.
    """
    print(f"[Background Task] Sending notification for agent: {agent.name}")
    print("[Background Task] Notification sent!")


# Create an agent with background post-hooks enabled
agent = Agent(
    id="background-task-agent",
    name="BackgroundTaskAgent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful assistant",
    db=SqliteDb(db_file="tmp/agent.db"),
    # Define hooks
    pre_hooks=[log_request],
    post_hooks=[log_analytics, send_notification],
    # Enable background mode for hooks
    run_hooks_in_background=True,
    markdown=True,
)

# Create AgentOS
agent_os = AgentOS(
    agents=[agent],
)

# Get the FastAPI app
app = agent_os.get_app()


# When you make a request to POST /agents/{agent_id}/runs:
# 1. The agent will process the request
# 2. The response will be sent immediately to the user
# 3. The pre-hooks (log_request) and post-hooks (log_analytics, send_notification) will run in the background
# 4. The user doesn't have to wait for these tasks to complete

# Example request:
# curl -X POST http://localhost:8000/agents/background-task-agent/runs \
#   -F "message=Hello, how are you?" \
#   -F "stream=false"

# The response will be returned immediately, while log_request, log_analytics and send_notification
# continue to run in the background without blocking the API response.

if __name__ == "__main__":
    agent_os.serve(app="background_hooks_example:app", port=7777, reload=True)
