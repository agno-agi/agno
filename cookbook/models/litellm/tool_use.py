from agno.agent import Agent
from agno.models.litellm import LiteLLMSDK
from agno.tools.duckduckgo import DuckDuckGoTools

openai_agent = Agent(
    model=LiteLLMSDK(
        id="gpt-4o",
        name="LiteLLM",
    ),
    markdown=True,
    tools=[DuckDuckGoTools()],
)

openai_agent.print_response("What's the age of Elon Musk")
