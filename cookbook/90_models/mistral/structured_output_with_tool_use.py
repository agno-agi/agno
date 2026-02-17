"""
Mistral Structured Output With Tool Use
=======================================

Cookbook example for `mistral/structured_output_with_tool_use.py`.
"""

from agno.agent import Agent
from agno.models.mistral import MistralChat
from agno.tools.websearch import WebSearchTools
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


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
    tools=[WebSearchTools()],
    output_schema=Person,
    add_datetime_to_context=True,
)

researcher.print_response("Find information about Elon Musk")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
