from agno.agent import Agent
from agno.models.cerebras import CerebrasOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=CerebrasOpenAI(id="llama-4-scout-17b-16e-instruct"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Whats happening in France?", stream=True)
