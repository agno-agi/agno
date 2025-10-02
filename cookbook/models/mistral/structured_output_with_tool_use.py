from agno.agent import Agent
from agno.models.mistral import MistralChat
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel


class Person(BaseModel):
    name: str
    description: str


model = MistralChat(
    id="mistral-medium-latest",
    temperature=0.0,
)

researcher = Agent(
    name="Researcher",
    model=model,
    role="You find people with a specific role at a provided company.",
    instructions=[
        "- Search the web for the person described"
        "- Find out if they have public contact details"
        "- Return the information in a structured format"
    ],
    tools=[DuckDuckGoTools()],
    output_schema=Person,
    add_datetime_to_context=True,
)

researcher.print_response("Find information about Elon Musk")
