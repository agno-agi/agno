from agno.agent import Agent, RunOutput  # noqa
from agno.models.vertexai.claude import Claude

agent = Agent(model=Claude(id="claude-sonnet-4@20250514", timeout=5), markdown=True)

agent.print_response("Share a 2 sentence horror story")
