from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="o3-mini"))

# Print the response in the terminal
agent.print_response("What is the closest galaxy to milky way?", stream=True)
