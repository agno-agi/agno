from agno.agent import Agent, RunOutput  # noqa
from agno.models.anthropic import Claude

agent = Agent(model=Claude(id="claude-sonnet-4-5-20250929", timeout=1.0), markdown=True)

agent.print_response("Share a 2 sentence horror story")
