"""Use Agno with Tuning Engines as an OpenAI-compatible endpoint."""

from os import getenv

from agno.agent import Agent
from agno.models.tuning_engines import TuningEngines

agent = Agent(
    model=TuningEngines(
        id=getenv("TUNING_ENGINES_MODEL", "gpt-5.6-luna"),
    ),
    markdown=True,
)

agent.print_response(
    "Explain how governance, traces, and usage reporting help production AI agents.",
    stream=True,
)
