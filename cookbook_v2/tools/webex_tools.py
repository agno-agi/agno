"""
Run `pip install openai webexpythonsdk` to install dependencies.
To get the Webex Teams Access token refer to - https://developer.webex.com/docs/bots

Steps:

1. Sign up for Webex Teams and go to the Webex [Developer Portal](https://developer.webex.com/)
2. Create the Bot
    2.1 Click in the top-right on your profile → My Webex Apps → Create a Bot.
    2.2 Enter Bot Name, Username, Icon, and Description, then click Add Bot.
3. Get the Access Token
    3.1 Copy the Access Token shown on the confirmation page (displayed once).
    3.2 If lost, regenerate it via My Webex Apps → Edit Bot → Regenerate Access Token.
4. Set the WEBEX_ACCESS_TOKEN environment variable
5. Launch Webex itself and add your bot to a space like the Welcome space. Use the bot's email address (e.g. test@webex.bot)
"""

from agno.agent import Agent
from agno.tools.webex import WebexTools

agent = Agent(tools=[WebexTools()], show_tool_calls=True)

# List all space in Webex
agent.print_response("List all space on our Webex", markdown=True)

# Send a message to a Space in Webex
agent.print_response(
    "Send a funny ice-breaking message to the webex Welcome space", markdown=True
)
