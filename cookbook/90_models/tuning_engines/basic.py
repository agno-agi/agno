"""Use Agno with Tuning Engines as an OpenAI-compatible endpoint."""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAILike

agent = Agent(
    model=OpenAILike(
        id=getenv("TUNING_ENGINES_MODEL", "gpt-4o"),
        api_key=getenv("TUNING_ENGINES_API_KEY"),
        base_url="https://api.tuningengines.com/v1",
    ),
    markdown=True,
)

agent.print_response(
    "Explain how governance, traces, and usage reporting help production AI agents.",
    stream=True,
)
