"""To use Ollama Cloud, you need to set the OLLAMA_API_KEY environment variable. Host is set to https://ollama.com by default. and set cloud_model=True or set host

If the model has been pulled into ollama cli, you can use it without setting those parameters

Read more here to find out how to pull model and setup API keys https://docs.ollama.com/cloud
"""

from agno.agent import Agent
from agno.models.ollama import Ollama

agent = Agent(
    model=Ollama(id="kimi-k2:1t-cloud",cloud_model=True,host="https://ollama.com"),
)

agent.print_response("What is the capital of France?", stream=True)
