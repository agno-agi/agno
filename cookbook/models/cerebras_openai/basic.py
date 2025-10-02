from agno.agent import Agent
from agno.models.cerebras import CerebrasOpenAI

agent = Agent(
    model=CerebrasOpenAI(id="llama-4-scout-17b-16e-instruct"),
    markdown=True,
)

# Print the response in the terminal
agent.print_response("write a two sentence horror story")
