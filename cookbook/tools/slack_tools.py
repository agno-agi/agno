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
            enable_get_channel_messages=False,
            enable_upload_file=False,
        )
    ],
    markdown=True,
)

# Example 3: Default behavior with all functions enabled
agent = Agent(
    tools=[
        SlackTools(
            enable_send_message=True,
            enable_list_channels=True,
            enable_get_channel_messages=True,
            enable_upload_file=True,
        )
    ],
    markdown=True,
)

# Example usage with all functions enabled
print("=== Example 1: Using all Slack functions ===")
agent_all.print_response(
    "Send a message 'Hello from Agno with all functions!' to the channel #bot-test and then list all channels", markdown=True
)

# Example usage with specific functions only
print("\n=== Example 2: Using specific Slack functions (send message + list channels) ===")
agent_specific.print_response(
    "Send a message 'Hello from limited bot!' to the channel #bot-test", markdown=True
)

# Example usage with default configuration
print("\n=== Example 3: Default Slack agent usage ===")
agent.print_response(
    "Send a message 'Hello from Agno!' to the channel #bot-test", markdown=True
)

agent.print_response("List all channels in our Slack workspace", markdown=True)

agent.print_response(
    "Get the last 10 messages from the channel #random-junk", markdown=True
)
