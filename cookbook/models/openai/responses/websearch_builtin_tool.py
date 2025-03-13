from agno.agent import Agent
from agno.models.openai import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    tools=[{"type": "web_search_preview"}],
    markdown=True,
)
agent.print_response("Whats happening in France?")