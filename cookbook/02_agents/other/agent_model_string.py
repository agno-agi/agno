"""Example showing how to set the model for an Agent using a model string"""

from agno.agent import Agent

# Model strings follow the format "{provider}:{model_id}", for example:
model_string = "openai:gpt-4o"

agent = Agent(model=model_string, markdown=True)

agent.print_response("Share a 2 sentence horror story")
