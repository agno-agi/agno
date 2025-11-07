"""
This example demonstrates output_schema override for agents.

Shows how to temporarily change the output schema for a single run
and have it automatically restored afterwards. Works with both
run/arun and streaming/non-streaming modes.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field
from rich.pretty import pprint


class PersonInfo(BaseModel):
    name: str = Field(..., description="Person's full name")
    age: int = Field(..., description="Person's age")
    occupation: str = Field(..., description="Person's occupation")


class BookInfo(BaseModel):
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Author name")
    year: int = Field(..., description="Publication year")


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    output_schema=PersonInfo,
    markdown=False,
)

# non-streaming with default schema
person_response = agent.run("Tell me about Albert Einstein", stream=False)
assert isinstance(person_response.content, PersonInfo)
pprint(person_response.content)

# non-streaming with schema override
print(f"Schema before override: {agent.output_schema.__name__}")
book_response = agent.run(
    "Tell me about '1984' by George Orwell", output_schema=BookInfo, stream=False
)
assert isinstance(book_response.content, BookInfo)
pprint(book_response.content)
print(f"Schema after override: {agent.output_schema.__name__}")
assert agent.output_schema == PersonInfo

# Streaming with schema override
print(f"\nSchema before override: {agent.output_schema.__name__}")
final_response = None
for event in agent.run(
    "Tell me about 'To Kill a Mockingbird'", output_schema=BookInfo, stream=True
):
    final_response = event

assert isinstance(final_response.content, BookInfo)
pprint(final_response.content)
assert agent.output_schema == PersonInfo
print(f"Schema after override: {agent.output_schema.__name__}")


# Async non-streaming with schema override
response = asyncio.run(agent.arun("Tell me about Marie Curie", stream=False))
assert isinstance(response.content, PersonInfo)
pprint(response.content)

print(f"\nSchema before override: {agent.output_schema.__name__}")
book_response = asyncio.run(
    agent.arun("Tell me about 'The Great Gatsby'", output_schema=BookInfo, stream=False)
)
assert isinstance(book_response.content, BookInfo)
pprint(book_response.content)
print(f"Schema after override: {agent.output_schema.__name__}")
assert agent.output_schema == PersonInfo


# Async streaming with schema override
async def async_streaming_example():
    print(f"\nSchema before override: {agent.output_schema.__name__}")
    final_response = None
    async for event in agent.arun(
        "Tell me about 'Pride and Prejudice'", output_schema=BookInfo, stream=True
    ):
        final_response = event
    assert isinstance(final_response.content, BookInfo)
    pprint(final_response.content)
    assert agent.output_schema == PersonInfo
    print(f"Schema after override: {agent.output_schema.__name__}")


asyncio.run(async_streaming_example())
