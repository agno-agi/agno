"""Telegram interface — long-polling mode.

Polling needs no public URL, no TLS, and no FastAPI server — ideal for local
development or machines behind NAT. Unlike webhook mode it is not mounted in an
AgentOS app; it runs standalone via run_polling().

Setup:
1. Create a bot with @BotFather and copy the token.
2. export TELEGRAM_TOKEN="..."
3. If you previously ran webhook mode for this bot, clear the webhook first:
   curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/deleteWebhook"
4. python cookbook/05_agent_os/interfaces/telegram/polling.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os.interfaces.telegram import Telegram

agent = Agent(
    name="Polling Bot",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You are a helpful assistant on Telegram.",
)

# mode="polling" runs without a web server; the token is read from TELEGRAM_TOKEN.
telegram_interface = Telegram(agent=agent, mode="polling")

if __name__ == "__main__":
    telegram_interface.run_polling()
