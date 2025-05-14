from typing import List

from agno.agent import Agent, RunEvent, RunResponse
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


async def test_async_streaming():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("Hi, my name is John", stream=True)

    chunks: List[RunResponse] = []
    async for chunk in response:
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


async def test_async_tool_streaming():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("Tell me the latest news in France", stream=True)

    chunks: List[RunResponse] = []
    tool_calls: bool = False

    async for chunk in response:
        chunks.append(chunk)
        if chunk.tools:
            tool_calls = True

    assert len(chunks) > 0
    assert tool_calls


def test_streaming_with_intermediate_steps():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        show_tool_calls=True,
        stream_intermediate_steps=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Tell me the latest news in France", stream=True)

    chunks: List[RunResponse] = []
    run_started: bool = False
    run_response: bool = False
    run_completed: bool = False

    for chunk in response:
        chunks.append(chunk)
        if chunk.event == RunEvent.run_started.value:
            run_started = True
        elif chunk.event == RunEvent.run_completed.value:
            run_completed = True
        elif chunk.event == RunEvent.run_response.value:
            run_response = True

    assert len(chunks) > 0
    assert run_started
    assert run_completed
    assert run_response


async def test_async_streaming_with_intermediate_steps():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        show_tool_calls=True,
        stream_intermediate_steps=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("Tell me the latest news in France", stream=True)

    chunks: List[RunResponse] = []
    run_started: bool = False
    run_completed: bool = False
    run_response: bool = False

    async for chunk in response:
        chunks.append(chunk)
        if chunk.event == RunEvent.run_started.value:
            run_started = True
        elif chunk.event == RunEvent.run_completed.value:
            run_completed = True
        elif chunk.event == RunEvent.run_response.value:
            run_response = True

    assert len(chunks) > 0
    assert run_started
    assert run_completed
    assert run_response


def test_tool_call_streaming_with_intermediate_steps():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        stream_intermediate_steps=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Tell me the latest news in France", stream=True)

    chunks: List[RunResponse] = []
    run_started: bool = False
    run_completed: bool = False
    run_response: bool = False
    tool_call_started: bool = False
    tool_call_completed: bool = False

    for chunk in response:
        chunks.append(chunk)
        if chunk.event == RunEvent.run_started.value:
            run_started = True
        elif chunk.event == RunEvent.run_completed.value:
            run_completed = True
        elif chunk.event == RunEvent.run_response.value:
            run_response = True
        elif chunk.event == RunEvent.tool_call_started.value:
            tool_call_started = True
        elif chunk.event == RunEvent.tool_call_completed.value:
            tool_call_completed = True

    assert len(chunks) > 0
    assert run_started
    assert run_completed
    assert run_response
    assert tool_call_started
    assert tool_call_completed


async def test_async_tool_call_streaming_with_intermediate_steps():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        stream_intermediate_steps=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("Tell me the latest news in France", stream=True)

    chunks: List[RunResponse] = []
    run_started: bool = False
    run_completed: bool = False
    run_response: bool = False
    tool_call_started: bool = False
    tool_call_completed: bool = False

    async for chunk in response:
        chunks.append(chunk)
        if chunk.event == RunEvent.run_started.value:
            run_started = True
        elif chunk.event == RunEvent.run_completed.value:
            run_completed = True
        elif chunk.event == RunEvent.run_response.value:
            run_response = True
        elif chunk.event == RunEvent.tool_call_started.value:
            tool_call_started = True
        elif chunk.event == RunEvent.tool_call_completed.value:
            tool_call_completed = True

    assert len(chunks) > 0
    assert run_started
    assert run_completed
    assert run_response
    assert tool_call_started
    assert tool_call_completed
