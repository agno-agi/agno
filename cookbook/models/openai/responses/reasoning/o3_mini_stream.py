from agno.agent import Agent
from agno.models.openai import OpenAIResponses

agent = Agent(model=OpenAIResponses(id="o3-mini"))

# Print the response in the terminal
agent.print_response("What is the closest galaxy to milky way?", stream=True)
