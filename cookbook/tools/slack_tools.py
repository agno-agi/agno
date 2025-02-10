"""Run `pip install openai slack-sdk` to install dependencies."""

from agno.agent import Agent
from agno.tools.slack import SlackTools

slack_tools = SlackTools()

agent = Agent(tools=[slack_tools], show_tool_calls=True)

# Example 1: Send a message to a Slack channel
agent.print_response(
    "Send a message 'Hello from Agno!' to the channel #bot-test", markdown=True
)

# Example 2: List all channels in the Slack workspace
agent.print_response("List all channels in our Slack workspace", markdown=True)

# Example 3: Get the message history of a specific channel
agent.print_response(
    "Get the last 10 messages from the channel #random-junk", markdown=True
)
