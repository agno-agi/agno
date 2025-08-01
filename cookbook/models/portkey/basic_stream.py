from agno.agent import Agent
from agno.models.portkey import Portkey

agent = Agent(
    model=Portkey(
        id="gpt-4o-mini",
    ),
    markdown=True,
)

# Print the response in the terminal
agent.print_response(
    "What is Portkey and why would I use it as an AI gateway?", stream=True
)
