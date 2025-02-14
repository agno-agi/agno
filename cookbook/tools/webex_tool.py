"""Run `pip install openai webexpythonsdk` to install dependencies."""

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