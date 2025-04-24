import asyncio
from dataclasses import dataclass

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel


async def dict_tool():
    return {"name": "John", "age": 30, "city": "New York"}


async def list_tool():
    return ["Hello", "World"]


async def set_tool():
    return {"apple", "banana", "cherry"}


async def tuple_tool():
    return ("John", 30, "New York")


async def generator_tool():
    for i in range(5):
        yield i


async def pydantic_tool():
    class CustomTool(BaseModel):
        name: str
        age: int
        city: str

    return CustomTool(name="John", age=30, city="New York")


async def data_class_tool():
    @dataclass
    class CustomTool:
        name: str
        age: int
        city: str

    return CustomTool(name="John", age=30, city="New York")


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        dict_tool,
        list_tool,
        generator_tool,
        pydantic_tool,
        data_class_tool,
        set_tool,
        tuple_tool,
    ],
    show_tool_calls=True,
)

asyncio.run(agent.aprint_response("Please call all the tools"))
