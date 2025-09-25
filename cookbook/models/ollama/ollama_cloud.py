"""To use Ollama Cloud, you need to set the OLLAMA_API_KEY environment variable. Host is set to https://ollama.com by default."""

from agno.agent import Agent
from agno.models.ollama import Ollama

agent = Agent(
    model=Ollama(id="gpt-oss:120b-cloud"),
)

agent.print_response("What is the capital of France?", stream=True)
