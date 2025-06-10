from agno.agent import Agent
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.0-flash", grounding=True),
    add_datetime_to_instructions=True,
)
agent.print_response(
    "Give me the latest details on Tariffs?", stream=True, markdown=True
)
