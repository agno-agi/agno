from agno.agent import Agent
from agno.models.cometapi import CometAPI

agent = Agent(model=CometAPI(id="gpt-5-mini"), markdown=True)

# Print the response in the terminal with streaming enabled
agent.print_response("Explain quantum computing in simple terms", stream=True)
