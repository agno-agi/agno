"""
Telegram Tools - Bot Communication and Messaging

This example demonstrates how to use TelegramTools for Telegram bot operations.
Shows enable_ flag patterns for selective function access.
TelegramTools is a small tool (<6 functions) so it uses enable_ flags.

Prerequisites:
- Create a new bot with BotFather on Telegram: https://core.telegram.org/bots/features#creating-a-new-bot
- Get the token from BotFather
- Send a message to the bot
- Get the chat_id by going to: https://api.telegram.org/bot<your-bot-token>/getUpdates
"""

from agno.agent import Agent
from agno.tools.telegram import TelegramTools

telegram_token = "<enter-your-bot-token>"
chat_id = "<enter-your-chat-id>"

# Example 1: All functions enabled (default behavior)
agent = Agent(
    name="telegram-full",
    tools=[
        TelegramTools(token=telegram_token, chat_id=chat_id)
    ],  # All functions enabled
    description="You are a comprehensive Telegram bot assistant with all messaging capabilities.",
    instructions=[
        "Help users with all Telegram bot operations",
        "Send messages, handle media, and manage bot interactions",
        "Provide clear feedback on bot operations",
        "Follow Telegram bot best practices",
    ],
    markdown=True,
)

agent.print_response("Send a message to the bot")
