"""Run: pip install openai slack-sdk"""

from agno.agent import Agent
from agno.tools.slack import SlackTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Enable all Slack tools
agent_all = Agent(
    tools=[
        SlackTools(
            all=True,  # Enable all Slack tools
        )
    ],
    markdown=True,
)

# Example 2: Enable specific tools only
agent_specific = Agent(
    tools=[
        SlackTools(
            enable_send_message=True,
            enable_list_channels=True,
            enable_get_channel_history=False,
            enable_upload_file=False,
            enable_download_file=False,
        )
    ],
    markdown=True,
)

# Example 3: Read-only agent (no send_message)
agent_readonly = Agent(
    tools=[
        SlackTools(
            enable_send_message=False,
            enable_list_channels=True,
            enable_get_channel_history=True,
            enable_upload_file=False,
            enable_download_file=True,
        )
    ],
    markdown=True,
)

# Run examples

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_all.print_response(
        "Send 'Hello from Agno!' to #general",
        stream=True,
    )

    agent_specific.print_response(
        "List all channels in the workspace",
        stream=True,
    )

    agent_readonly.print_response(
        "Get the last 5 messages from #general",
        stream=True,
    )
