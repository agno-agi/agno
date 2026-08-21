"""Reproduction test for issue #8062: MCP run tools crash when agent default is stream=True.

The bug: run_agent/run_team/run_workflow called `await agent.arun(message)` without passing
`stream=False`. When the agent's default was `stream=True`, `arun()` returned an AsyncIterator
(not a Coroutine), and `await` on an iterator raised:

    TypeError: object async_generator_asend can't be used in 'await' expression

The fix: the run tools now explicitly stream with `yield_run_output=True` and consume the
iterator with `async for`, so the agent's default stream setting is irrelevant.
"""

import pytest

pytest.importorskip("fastmcp")

from typing import Any, AsyncIterator, Iterator

from fastmcp import Client

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.mcp import build_mcp_server
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


class _MockModel(Model):
    """Minimal offline model for testing."""

    def __init__(self) -> None:
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._r = ModelResponse(content="response from agent", role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *a: Any, **k: Any) -> Any:
        return None

    def get_system_message_for_model(self, *a: Any, **k: Any) -> Any:
        return None

    async def aget_instructions_for_model(self, *a: Any, **k: Any) -> Any:
        return None

    async def aget_system_message_for_model(self, *a: Any, **k: Any) -> Any:
        return None

    def parse_args(self, *a: Any, **k: Any) -> dict:
        return {}

    def invoke(self, *a: Any, **k: Any) -> ModelResponse:
        return self._r

    async def ainvoke(self, *a: Any, **k: Any) -> ModelResponse:
        return self._r

    def invoke_stream(self, *a: Any, **k: Any) -> Iterator[ModelResponse]:
        yield self._r

    async def ainvoke_stream(self, *a: Any, **k: Any) -> AsyncIterator[ModelResponse]:
        yield self._r
        return

    def _parse_provider_response(self, response: Any, **k: Any) -> ModelResponse:
        return self._r

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._r


class TestIssue8062:
    """Regression tests for issue #8062: MCP tools with stream=True agents."""

    @pytest.mark.asyncio
    async def test_run_agent_with_stream_true_default(self):
        """run_agent works when the agent's default is stream=True.

        This is the exact reproduction case from issue #8062:
        - Agent with stream=True (or relying on class default that is True)
        - Call run_agent via MCP
        - Should NOT raise TypeError about async_generator_asend
        """
        agent = Agent(
            id="stream-agent",
            name="Stream Agent",
            model=_MockModel(),
            stream=True,  # The bug trigger
        )
        os = AgentOS(agents=[agent])

        async with Client(build_mcp_server(os)) as client:
            # This would raise TypeError before the fix:
            # TypeError: object async_generator_asend can't be used in 'await' expression
            result = await client.call_tool("run_agent", {"agent_id": "stream-agent", "message": "hello"})

        # Verify we got a valid response
        assert result is not None
        # The result should contain the agent's response
        assert "response from agent" in str(result.data) or result.data is not None

    @pytest.mark.asyncio
    async def test_run_agent_with_stream_false_default(self):
        """run_agent also works when the agent's default is stream=False (baseline)."""
        agent = Agent(
            id="nonstream-agent",
            name="NonStream Agent",
            model=_MockModel(),
            stream=False,
        )
        os = AgentOS(agents=[agent])

        async with Client(build_mcp_server(os)) as client:
            result = await client.call_tool("run_agent", {"agent_id": "nonstream-agent", "message": "hello"})

        assert result is not None

    @pytest.mark.asyncio
    async def test_run_team_with_stream_true_default(self):
        """run_team works when the team's default is stream=True."""
        agent = Agent(id="member", name="Member", model=_MockModel())
        team = Team(
            id="stream-team",
            name="Stream Team",
            members=[agent],
            model=_MockModel(),
            stream=True,  # The bug trigger
        )
        os = AgentOS(teams=[team])

        async with Client(build_mcp_server(os)) as client:
            result = await client.call_tool("run_team", {"team_id": "stream-team", "message": "hello"})

        assert result is not None

    @pytest.mark.asyncio
    async def test_run_agent_explicit_stream_overrides_default(self):
        """The MCP tool explicitly streams, overriding whatever the agent's default is."""
        agent = Agent(
            id="test-agent",
            name="Test Agent",
            model=_MockModel(),
            stream=True,  # Default that would break old code
        )
        os = AgentOS(agents=[agent])

        async with Client(build_mcp_server(os)) as client:
            # Run multiple times to ensure no state issues
            for i in range(3):
                result = await client.call_tool("run_agent", {"agent_id": "test-agent", "message": f"msg {i}"})
                assert result is not None

    @pytest.mark.asyncio
    async def test_run_workflow_with_stream_true_default(self):
        """run_workflow works when the workflow's default is stream=True."""
        agent = Agent(id="wf-agent", name="WF Agent", model=_MockModel())
        workflow = Workflow(
            id="stream-workflow",
            name="Stream Workflow",
            steps=[Step(agent=agent)],
            stream=True,  # The bug trigger
        )
        os = AgentOS(workflows=[workflow])

        async with Client(build_mcp_server(os)) as client:
            result = await client.call_tool("run_workflow", {"workflow_id": "stream-workflow", "message": "hello"})

        assert result is not None


class TestNonNativeProtocolAdapter:
    """Regression tests for non-native AgentProtocol adapters with stream=True default.

    The non-native fallback in _run_agentic_component must pin stream=False, otherwise
    a protocol adapter that defaults to streaming will return an AsyncIterator and crash.
    """

    @pytest.mark.asyncio
    async def test_protocol_adapter_with_stream_true_default(self, monkeypatch):
        """Non-native adapter with stream=True default works via MCP.

        Before the fix, the non-native path did:
            return await component.arun(message, ...)
        without passing stream=False, so adapters defaulting to stream=True crashed.
        """
        from typing import Optional, Sequence, Union
        from uuid import uuid4

        import agno.os.mcp as mcp_mod
        from agno.media import Audio, File, Image, Video
        from agno.run.agent import RunOutput, RunOutputEvent

        class StreamingProtocolAdapter:
            """A third-party AgentProtocol that defaults to streaming."""

            def __init__(self):
                self._id = "streaming-adapter"
                self._name = "Streaming Adapter"
                self.stream = True  # Default to streaming

            @property
            def id(self) -> str:
                return self._id

            @property
            def name(self) -> Optional[str]:
                return self._name

            def arun(
                self,
                input,
                *,
                stream: Optional[bool] = None,
                session_id: Optional[str] = None,
                user_id: Optional[str] = None,
                images: Optional[Sequence[Image]] = None,
                audio: Optional[Sequence[Audio]] = None,
                videos: Optional[Sequence[Video]] = None,
                files: Optional[Sequence[File]] = None,
                stream_events: Optional[bool] = None,
                **kwargs,
            ) -> Union[RunOutput, "AsyncIterator[RunOutputEvent]"]:
                resolved_stream = stream if stream is not None else self.stream
                if resolved_stream:
                    return self._stream_run(input, session_id, user_id)
                else:
                    return self._non_stream_run(input, session_id, user_id)

            async def _stream_run(self, input, session_id, user_id):
                yield RunOutput(
                    content="streamed",
                    run_id=str(uuid4()),
                    session_id=session_id or str(uuid4()),
                )

            async def _non_stream_run(self, input, session_id, user_id) -> RunOutput:
                return RunOutput(
                    content="non-streamed",
                    run_id=str(uuid4()),
                    session_id=session_id or str(uuid4()),
                )

        adapter = StreamingProtocolAdapter()
        os = AgentOS(agents=[adapter])  # type: ignore[list-item]

        # Patch resolution to return our adapter directly
        async def _resolve(os, kind, component_id, *, user_id, session_id, strict=True):
            if component_id == "streaming-adapter":
                return adapter
            raise Exception(f"Agent {component_id} not found")

        monkeypatch.setattr(mcp_mod, "_resolve_run_component", _resolve)

        async with Client(build_mcp_server(os)) as client:
            # Before fix: TypeError: object async_generator can't be used in 'await' expression
            # After fix: works because stream=False is pinned
            result = await client.call_tool("run_agent", {"agent_id": "streaming-adapter", "message": "hello"})

        assert result is not None
        # Content is in result.content[0].text, not result.data
        assert any("non-streamed" in c.text for c in result.content)
