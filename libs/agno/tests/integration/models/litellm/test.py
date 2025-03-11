from agno.agent import Agent
from agno.models.litellm import LiteLLMSDK
from agno.tools.duckduckgo import DuckDuckGoTools


openai_agent = Agent(
    model=LiteLLMSDK(
        id="huggingface/mistralai/Mistral-7B-Instruct-v0.2",
        top_p=0.95,
    ),
    markdown=True,
)

openai_agent.print_response("Give a basic add function in python")
