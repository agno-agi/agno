from agno.agent import Agent
from agno.models.ollama import Ollama

reasoning_agent = Agent(
    model=Ollama(id="gpt-oss:120b"),
    reasoning=True,
    debug_mode=True,
)

reasoning_agent.print_response(
    "How many r are in the word 'strawberry'?", show_reasoning=True
)
