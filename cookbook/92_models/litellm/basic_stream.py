from agno.agent import Agent
from agno.models.litellm import LiteLLM

openai_agent = Agent(
    model=LiteLLM(
        id="gpt-4o",
        name="LiteLLM",
    ),
    markdown=True,
)

openai_agent.print_response("Share a 2 sentence horror story", stream=True)
