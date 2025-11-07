"""
This example demonstrates output_schema override for teams.

Shows how to temporarily change the output schema for a single run
and have it automatically restored afterwards. Works with both
run/arun and streaming/non-streaming modes.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel
from rich.pretty import pprint


class PersonSchema(BaseModel):
    name: str
    age: int


class BookSchema(BaseModel):
    title: str
    author: str
    year: int


researcher = Agent(
    name="Researcher",
    model=OpenAIChat("gpt-4o"),
    role="Researches information.",
    tools=[DuckDuckGoTools()],
)

team = Team(
    name="Research Team",
    model=OpenAIChat("gpt-4o"),
    members=[researcher],
    output_schema=PersonSchema,
    markdown=False,
)

response = team.run("Tell me about Albert Einstein", stream=False)
assert isinstance(response.content, PersonSchema)
pprint(response.content)

print(f"\nSchema before override: {team.output_schema.__name__}")
book_response = team.run(
    "Tell me about '1984' by George Orwell", output_schema=BookSchema, stream=False
)
assert isinstance(book_response.content, BookSchema)
pprint(book_response.content)
print(f"Schema after override: {team.output_schema.__name__}")
assert team.output_schema == PersonSchema

print(f"\nSchema before override: {team.output_schema.__name__}")
run_response = None
for event_or_response in team.run(
    "Tell me about 'To Kill a Mockingbird'", output_schema=BookSchema, stream=True
):
    run_response = event_or_response

assert isinstance(run_response.content, BookSchema)
pprint(run_response.content)
assert team.output_schema == PersonSchema
print(f"Schema after override: {team.output_schema.__name__}")


async def test_async_override():
    """Test async with schema override."""
    response = await team.arun("Tell me about Marie Curie", stream=False)
    assert isinstance(response.content, PersonSchema)
    pprint(response.content)

    print(f"\nSchema before override: {team.output_schema.__name__}")
    book_response = await team.arun(
        "Tell me about 'The Great Gatsby'", output_schema=BookSchema, stream=False
    )
    assert isinstance(book_response.content, BookSchema)
    pprint(book_response.content)
    assert team.output_schema == PersonSchema
    print(f"Schema after override: {team.output_schema.__name__}")


async def test_async_streaming_override():
    """Test async streaming with schema override."""
    print(f"\nSchema before override: {team.output_schema.__name__}")
    run_response = None
    async for event_or_response in team.arun(
        "Tell me about 'Pride and Prejudice'", output_schema=BookSchema, stream=True
    ):
        run_response = event_or_response

    assert isinstance(run_response.content, BookSchema)
    pprint(run_response.content)
    assert team.output_schema == PersonSchema
    print(f"Schema after override: {team.output_schema.__name__}")


if __name__ == "__main__":
    asyncio.run(test_async_override())
    asyncio.run(test_async_streaming_override())
