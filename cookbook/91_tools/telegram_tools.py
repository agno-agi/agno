"""
Telegram Tools
==============

Environment variables:
    TELEGRAM_TOKEN      Bot token from @BotFather
    TELEGRAM_CHAT_ID    Chat ID to send messages to

Get chat_id: https://api.telegram.org/bot<token>/getUpdates
"""

from agno.agent import Agent
from agno.tools.telegram import TelegramTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Enable all Telegram tools
agent_all = Agent(
    tools=[
        TelegramTools(
            all=True,  # Enable all tools including pin_message, get_chat, get_file
        )
    ],
    markdown=True,
)

# Example 2: Messaging only (default)
agent_messaging = Agent(
    tools=[
        TelegramTools(
            enable_send_message=True,
            enable_edit_message=True,
            enable_delete_message=True,
        )
    ],
    markdown=True,
)

# Example 3: With file downloads saved to disk
agent_downloads = Agent(
    tools=[
        TelegramTools(
            enable_send_message=True,
            enable_get_file=True,
            save_downloads=True,
            output_directory="/tmp/telegram_downloads",
        )
    ],
    markdown=True,
)

# Example 4: Reactions and pinning
agent_reactions = Agent(
    tools=[
        TelegramTools(
            enable_send_message=True,
            enable_react_with_emoji=True,
            enable_pin_message=True,
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_all.print_response(
        "Send 'Hello from Agno!' to the chat",
        stream=True,
    )

    # agent_messaging.print_response(
    #     "Send 'Testing edit' then edit it to say 'Message edited!'",
    #     stream=True,
    # )

    # agent_downloads.print_response(
    #     "Send a test message to the chat",
    #     stream=True,
    # )

    # agent_reactions.print_response(
    #     "Send 'Test pinned message' and pin it",
    #     stream=True,
    # )
