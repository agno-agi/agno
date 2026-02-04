"""
Slack Tools - Send messages, manage channels, search, and upload files to Slack.

Prerequisites:
    pip install openai slack-sdk

Environment variables:
    SLACK_TOKEN - Slack bot token (xoxb-...) for most operations
    OPENAI_API_KEY - For agent examples

Available Tools (10 total):
    - send_message: Send a message to a channel
    - send_message_thread: Reply to a message in a thread
    - list_channels: List all channels in the workspace
    - get_channel_history: Read messages from a channel
    - get_thread: Get all replies in a thread
    - upload_file: Upload a file (supports str or bytes content)
    - download_file: Download a file by ID
    - list_users: List all users in the workspace
    - get_user_info: Get details about a specific user
    - search_messages: Search messages (requires User Token - see below)

Required Bot Token Scopes (xoxb-):
    chat:write - Send messages
    channels:read - List channels
    channels:history - Read channel messages
    files:write - Upload files
    files:read - Download files
    users:read - List users and get user info

User Token for Search (xoxp-):
    The search_messages tool requires a User OAuth Token, not a Bot Token.
    Add 'search:read' to User Token Scopes in your Slack app settings,
    then reinstall the app to generate the user token.

    To use search_messages:
        tools = SlackTools(token="xoxp-your-user-token")
        tools.search_messages(query="keyword")
"""

from agno.agent import Agent
from agno.tools.slack import SlackTools

# Example 1: Enable all Slack functions
agent_all = Agent(
    tools=[
        SlackTools(
            all=True,  # Enable all Slack functions
        )
    ],
    instructions=[
        "You are a Slack assistant that can send messages, read channels, and manage files.",
        "Use markdown formatting in messages: *bold*, _italic_, `code`.",
    ],
    markdown=True,
)

# Example 2: Enable specific Slack functions only
agent_specific = Agent(
    tools=[
        SlackTools(
            enable_send_message=True,
            enable_send_message_thread=True,
            enable_list_channels=True,
            enable_get_channel_history=False,
            enable_upload_file=False,
            enable_download_file=False,
        )
    ],
    instructions=[
        "You are a Slack assistant that can send messages and list channels.",
        "You cannot read message history or manage files.",
    ],
    markdown=True,
)

# Example 3: Read-only agent (no message sending)
agent_readonly = Agent(
    tools=[
        SlackTools(
            enable_send_message=False,
            enable_send_message_thread=False,
            enable_list_channels=True,
            enable_get_channel_history=True,
            enable_upload_file=False,
            enable_download_file=True,
        )
    ],
    instructions=[
        "You are a Slack assistant that can only read channel data.",
        "You cannot send messages or upload files.",
    ],
    markdown=True,
)

# Example usage: Agent discovers channels and sends message
print("=== Example 1: Send message to a channel ===")
agent_all.print_response(
    "Send the message 'Hello from Agno!' to the #general channel",
    stream=True,
)

# Example usage: List available channels
print("\n=== Example 2: List channels ===")
agent_specific.print_response(
    "List all channels in the workspace",
    stream=True,
)

# Example usage: Read channel history
print("\n=== Example 3: Read channel history ===")
agent_readonly.print_response(
    "Get the last 5 messages from the #general channel",
    stream=True,
)

# Example: Send formatted message with markdown
# agent_all.print_response(
#     "Send a message to #general with a *bold title*, a bullet list of 3 items, and a link to https://docs.agno.com",
#     stream=True,
# )

# Example: Send a thread reply
# agent_all.print_response(
#     "Send 'Starting thread!' to #general, then reply to that message with 'This is a reply!'",
#     stream=True,
# )

# Example: Upload a file
# agent_all.print_response(
#     "Create a CSV file with sample sales data and upload it to #general with a comment explaining the data",
#     stream=True,
# )

# Example: Read and summarize channel
# agent_readonly.print_response(
#     "Read the last 10 messages from #general and summarize the main topics discussed",
#     stream=True,
# )
