from agno.agent import Agent
from agno.tools.telegram import TelegramTools

# How to get the token and chat_id:
# 1. Create a new bot with BotFather on Telegram. https://core.telegram.org/bots/features#creating-a-new-bot
# 2. Get the token from BotFather.
# 3. Send a message to the bot.
# 4. Get the chat_id by going to the URL:
#    https://api.telegram.org/bot<your-bot-token>/getUpdates

telegram_token = "<enter-your-bot-token>"
chat_id = "<enter-your-chat-id>"

agent = Agent(
    name="telegram",
    tools=[TelegramTools(token=telegram_token, chat_id=chat_id)],
)

agent.print_response("Send message to telegram chat a paragraph about the moon")
