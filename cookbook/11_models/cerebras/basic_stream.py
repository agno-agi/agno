from agno.agent import Agent  # noqa
from agno.models.cerebras import Cerebras

agent = Agent(
    model=Cerebras(id="llama-3.3-70b"),
    markdown=True,
)

# Print the response in the terminal
agent.print_response("write a two sentence horror story", stream=True)
