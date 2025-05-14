from typing import List

from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools


def test_streaming():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Hi, my name is John", stream=True)

    chunks: List[RunResponse] = []
    for chunk in response:
        chunks.append(chunk)

    assert len(chunks) > 0
    assert chunks[0].content is not None
    assert chunks[-1].content is not None
    assert chunks[0].content != chunks[-1].content


def test_tool_streaming():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Tell me the latest news in France", stream=True)

    chunks: List[RunResponse] = []
    tool_calls: bool = False

    for chunk in response:
        chunks.append(chunk)
        if chunk.tools:
            tool_calls = True

    assert len(chunks) > 0
    assert tool_calls
