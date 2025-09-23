"""Use hosted models from Ollama.com. support api_key parameter or OLLAMA_API_KEY environment variable."""

from agno.agent import Agent
from agno.models.ollama import Ollama

agent = Agent(
    model=Ollama(id="deepseek-v3.1:671b", host="https://ollama.com"),
)

agent.print_response("How many r's in the word 'strawberry'?", stream=True)
