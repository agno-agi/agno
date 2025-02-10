from agno.agent import Agent, RunResponse  # noqa
from agno.models.ollama import Ollama
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Ollama(id="qwen2.5:latest "), tools=[DuckDuckGoTools()], markdown=True
)

# Print the response in the terminal
agent.print_response("What is happening in France?")
