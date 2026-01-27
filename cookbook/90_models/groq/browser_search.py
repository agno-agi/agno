from agno.agent import Agent
from agno.models.groq import Groq

agent = Agent(
    model=Groq(id="openai/gpt-oss-20b"),
    tools=[{"type": "browser_search"}],
)
agent.print_response("Is the Going-to-the-sun road open for public?")
