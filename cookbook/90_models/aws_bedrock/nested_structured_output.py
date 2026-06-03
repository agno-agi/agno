"""Test nested Pydantic schemas with AWS Bedrock structured outputs.

This verifies that nested models (which use $defs in JSON Schema) work correctly
with Bedrock's native structured output support.
"""

from agno.agent import Agent
from agno.models.aws import AwsBedrock
from pydantic import BaseModel


class Character(BaseModel):
    name: str
    role: str


class Movie(BaseModel):
    title: str
    year: int
    characters: list[Character]


agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    output_schema=Movie,
    markdown=True,
)

response = agent.run(
    "Tell me about The Matrix (1999). Include at least 3 main characters."
)
print(response.content)
print()
print("Characters:")
for char in response.content.characters:
    print(f"  - {char.name}: {char.role}")
