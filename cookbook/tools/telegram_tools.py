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
agent_full = Agent(
    name="telegram-full",
    tools=[TelegramTools(token=telegram_token, chat_id=chat_id)],  # All functions enabled
    description="You are a comprehensive Telegram bot assistant with all messaging capabilities.",
    instructions=[
        "Help users with all Telegram bot operations",
        "Send messages, handle media, and manage bot interactions",
        "Provide clear feedback on bot operations",
        "Follow Telegram bot best practices",
    ],
    markdown=True,
)

# Example 2: Enable only message sending
agent_send_only = Agent(
    name="telegram-sender",
    tools=[TelegramTools(
        token=telegram_token,
        chat_id=chat_id,
        enable_send_message=True,
        enable_send_photo=False,     # Disable media sending
        enable_get_updates=False,    # Disable message receiving
    )],
    description="You are a Telegram message sender focused on text communication only.",
    instructions=[
        "Send text messages through Telegram bot",
        "Cannot send media or receive messages", 
        "Focus on simple text-based communication",
        "Ensure message formatting is clear",
    ],
    markdown=True,
)

# Example 3: Enable all functions using 'all=True' pattern
agent_comprehensive = Agent(
    name="telegram-comprehensive", 
    tools=[TelegramTools(token=telegram_token, chat_id=chat_id, all=True)],
    description="You are a full-featured Telegram bot with all capabilities enabled.",
    instructions=[
        "Manage complete Telegram bot operations",
        "Handle messages, media, and bot administration",
        "Provide comprehensive bot functionality",
        "Support advanced bot features and workflows",
    ],
    markdown=True,
)

# Example 4: Read-only bot (receive messages only)
agent_receiver = Agent(
    name="telegram-receiver",
    tools=[TelegramTools(
        token=telegram_token,
        chat_id=chat_id,
        enable_send_message=False,   # Disable sending
        enable_get_updates=True,     # Enable receiving messages
    )],
    description="You are a Telegram message receiver focused on monitoring conversations.",
    instructions=[
        "Monitor and analyze incoming Telegram messages",
        "Cannot send messages or media",
        "Focus on message processing and analysis",
        "Provide insights about conversation patterns",
    ],
    markdown=True,
)

# Example usage
print("=== Basic Message Sending Example ===")
agent_send_only.print_response("Send message to telegram chat a paragraph about the moon")

print("\n=== Comprehensive Bot Example ===")
agent_comprehensive.print_response("""
Set up a complete interaction:
1. Send a welcome message about space exploration
2. Check for any recent messages from users
3. Respond with interesting facts about astronomy
""")

print("\n=== Full-Featured Bot Example ===")
agent_full.print_response("Send an informative message about the latest space discoveries")
