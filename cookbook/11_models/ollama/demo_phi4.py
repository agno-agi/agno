from agno.agent import Agent, RunOutput  # noqa
from agno.models.ollama import Ollama

agent = Agent(model=Ollama(id="phi4"), markdown=True)

# Print the response in the terminal
agent.print_response("Tell me a scary story in exactly 10 words.")
