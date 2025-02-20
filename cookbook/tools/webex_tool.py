"""
Run `pip install openai webexpythonsdk` to install dependencies.
To get Access token refer - https://developer.webex.com/docs/bots

Steps (refer link for updated)

1. Create the Bot
    1.1 Log in to Webex → My Webex Apps → Create a New App → Create a Bot.
    1.2 Enter Bot Name, Username, Icon, and Description, then click Add Bot.
2.Get the Access Token
    2.1 Copy the Access Token shown on the confirmation page (displayed once).
    2.2 If lost, regenerate it via My Webex Apps → Edit Bot → Regenerate Access Token.
"""

import os

from agno.agent import Agent
from agno.tools.webex import WebexTools

webex_token = os.getenv("WEBEX_TEAMS_ACCESS_TOKEN")
webex_tool = WebexTools(token=webex_token)

agent = Agent(tools=[webex_tool], show_tool_calls=True)

#Send a message to a Space in Webex
agent.print_response("Send a funny ice-breaking message to the webex Welcome space", markdown=True)

#List all space in Webex
agent.print_response("List all space on our Webex", markdown=True)
