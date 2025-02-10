from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai import OpenAIChat

# This will only work if you have access to the o1 model from OpenAI
agent = Agent(model=OpenAIChat(id="o1"))

# Print the response in the terminal
agent.print_response("What is the closest galaxy to milky way?")
