"""Run `pip install openai slack-sdk` to install dependencies."""

from agno.agent import Agent
from agno.tools.slack import SlackTools

# Example 1: Enable all Slack functions
agent_all = Agent(
    tools=[
        SlackTools(
            all=True,  # Enable all Slack functions
        )
    ],
    markdown=True,
)

# Example 2: Enable specific Slack functions only
agent_specific = Agent(
    tools=[
        SlackTools(
            enable_send_message=True,
            enable_list_channels=True,
            enable_get_channel_history=False,
            enable_send_message_thread=False,
        )
    ],
    markdown=True,
)


# Example usage with all functions enabled
print("=== Example 1: Using all Slack functions ===")
agent_all.print_response(
    "Send a message 'Hello from Agno with all functions!' to the channel #bot-test and then list all channels",
    markdown=True,
)

# Example usage with specific functions only
print(
    "\n=== Example 2: Using specific Slack functions (send message + list channels) ==="
)
agent_specific.print_response(
    "Send a message 'Hello from limited bot!' to the channel #bot-test", markdown=True
)

# Example slack markdown formatting
print("\n=== Example 3: Slack Markdown Formatting (enabled by default) ===")
agent_all.print_response(
    "Send a message to #bot-test with *bold text*, _italic text_, and a `code snippet`",
    markdown=True,
)
