"""Checked by test_external_agent_dx.py with mypy; never makes model calls."""

from typing import TYPE_CHECKING, Any, AsyncIterator, Coroutine, Iterator, Union

from typing_extensions import assert_type

from agno.agent.protocol import AgentProtocol
from agno.agents.claude import ClaudeAgent
from agno.run.agent import RunOutput, RunOutputEvent

if TYPE_CHECKING:
    agent = ClaudeAgent(model="example", tools=[])
    assert_type(agent.run("hello"), RunOutput)
    assert_type(agent.run("hello", stream=True), Iterator[RunOutputEvent])
    assert_type(agent.run("hello", stream=True, yield_run_output=True), Iterator[Union[RunOutputEvent, RunOutput]])
    _ = assert_type(agent.arun("hello"), Coroutine[Any, Any, RunOutput])
    assert_type(agent.arun("hello", stream=True), AsyncIterator[RunOutputEvent])
    assert_type(
        agent.arun("hello", stream=True, yield_run_output=True), AsyncIterator[Union[RunOutputEvent, RunOutput]]
    )
    assert_type(agent.arun("hello", stream=True, background=True), AsyncIterator[str])
    assert_type(
        agent.arun("hello", stream=True, background=True, yield_run_output=True), AsyncIterator[Union[str, RunOutput]]
    )
    assert_type(agent.print_response("hello"), RunOutput)
    _ = assert_type(agent.aprint_response("hello"), Coroutine[Any, Any, RunOutput])
    protocol: AgentProtocol = agent
    protocol_result = assert_type(
        protocol.arun("hello"),
        Union[Coroutine[Any, Any, RunOutput], AsyncIterator[Union[RunOutputEvent, RunOutput, str]]],
    )
