from agno.agent import Agent
from agno.models.litellm import LiteLLMSDK

openai_agent = Agent(
    model=LiteLLMSDK(
        id="gpt-4o",
        name="LiteLLM",
    ),
    markdown=True,
)

openai_agent.print_response("Share a 2 sentence horror story")
