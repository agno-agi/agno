from agno.agent import Agent
from agno.models.cerebras import Cerebras
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Cerebras(id="llama-4-scout-17b-16e-instruct"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

# Print the response in the terminal
agent.print_response("Whats happening in France?")
