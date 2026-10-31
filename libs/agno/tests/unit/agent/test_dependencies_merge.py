"""Regression tests: call-site ``dependencies`` merge with ``Agent.dependencies``.

Bug: call-site dependencies (e.g. channel/thread ids injected by the Slack/WhatsApp
interfaces) used to REPLACE ``Agent.dependencies`` wholesale, so prompt-template
variables configured on the agent silently dropped out of the system/user messages on
those surfaces. They must merge instead, with call-site keys winning on conflict.

These tests run the full ``run()`` / ``arun()`` path against a mock model (no network)
and assert the rendered system message — the same message an interface would send.
"""

from copy import deepcopy
from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunInput, RunOutput


class MockModel(Model):
    """Minimal offline model: returns a canned text response without any network call."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="ok",
            role="assistant",
            response_usage=MessageMetrics(),
        )

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def _system_content(response) -> str:
    """The system message is the first message sent to the model."""
    return response.messages[0].content


# ---------------------------------------------------------------------------
# Sync: run()
# ---------------------------------------------------------------------------


class TestRunDependenciesMerge:
    def test_agent_template_var_survives_callsite_runtime_keys(self):
        """The core bug: an interface passes runtime context deps; agent template vars must remain."""
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x}",
        )
        # Simulate what Slack/WhatsApp do: pass call-site deps that do NOT include the agent's key.
        response = agent.run("hi", dependencies={"channel": "C123"})
        assert "X=RESOLVED" in _system_content(response)

    def test_callsite_key_also_available_for_substitution(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x} Z={z}",
        )
        response = agent.run("hi", dependencies={"z": "1"})
        assert "X=RESOLVED Z=1" in _system_content(response)

    def test_callsite_key_overrides_agent_key_on_conflict(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "agent"},
            instructions="X={x}",
        )
        response = agent.run("hi", dependencies={"x": "call"})
        assert "X=call" in _system_content(response)

    def test_no_callsite_deps_agent_deps_still_resolve(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x}",
        )
        response = agent.run("hi")
        assert "X=RESOLVED" in _system_content(response)

    def test_resolver_callable_merges_with_callsite(self):
        def resolve_x():
            return "RESOLVED"

        agent = Agent(
            model=MockModel(),
            dependencies={"x": resolve_x},
            instructions="X={x} Z={z}",
        )
        response = agent.run("hi", dependencies={"z": "1"})
        assert "X=RESOLVED Z=1" in _system_content(response)


# ---------------------------------------------------------------------------
# Async: arun()
# ---------------------------------------------------------------------------


class TestArunDependenciesMerge:
    @pytest.mark.asyncio
    async def test_agent_template_var_survives_callsite_runtime_keys(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x}",
        )
        response = await agent.arun("hi", dependencies={"channel": "C123"})
        assert "X=RESOLVED" in _system_content(response)

    @pytest.mark.asyncio
    async def test_callsite_key_also_available_for_substitution(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x} Z={z}",
        )
        response = await agent.arun("hi", dependencies={"z": "1"})
        assert "X=RESOLVED Z=1" in _system_content(response)

    @pytest.mark.asyncio
    async def test_callsite_key_overrides_agent_key_on_conflict(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "agent"},
            instructions="X={x}",
        )
        response = await agent.arun("hi", dependencies={"x": "call"})
        assert "X=call" in _system_content(response)

    @pytest.mark.asyncio
    async def test_no_callsite_deps_agent_deps_still_resolve(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x}",
        )
        response = await agent.arun("hi")
        assert "X=RESOLVED" in _system_content(response)

    @pytest.mark.asyncio
    async def test_async_resolver_callable_merges_with_callsite(self):
        async def resolve_x():
            return "RESOLVED"

        agent = Agent(
            model=MockModel(),
            dependencies={"x": resolve_x},
            instructions="X={x} Z={z}",
        )
        response = await agent.arun("hi", dependencies={"z": "1"})
        assert "X=RESOLVED Z=1" in _system_content(response)


class RecordingModel(MockModel):
    def __init__(self, content="ok", fail_first=False):
        super().__init__()
        self.calls = []
        self.fail_first = fail_first
        self._mock_response.content = content

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(deepcopy([(m.role, m.content) for m in messages]))
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("transient model failure")
        return self._mock_response

    async def ainvoke(self, messages, *args, **kwargs):
        return self.invoke(messages, *args, **kwargs)

    def invoke_stream(self, messages, *args, **kwargs):
        yield self.invoke(messages, *args, **kwargs)

    async def ainvoke_stream(self, messages, *args, **kwargs):
        yield self.invoke(messages, *args, **kwargs)


async def _execute(agent, *, async_mode, stream, continuing=False, **kwargs):
    if async_mode:
        method = agent.acontinue_run if continuing else agent.arun
        result = method(stream=stream, yield_run_output=stream, **kwargs)
        if stream:
            outputs = [event async for event in result if isinstance(event, RunOutput)]
            return outputs[-1]
        return await result
    method = agent.continue_run if continuing else agent.run
    result = method(stream=stream, yield_run_output=stream, **kwargs)
    if stream:
        return [event for event in result if isinstance(event, RunOutput)][-1]
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_dependency_input_session_and_prompt_equivalence(async_mode, stream):
    """Current input/history injection preserves explicit prompt and follow-up inputs."""
    calls = []

    def resolve(run_input, session, agent, run_context):
        assert isinstance(run_input, RunInput)
        assert agent is dependency_agent
        assert session.session_id == run_context.session_id == "test-session"
        assert run_context.session_state is not None
        previous = [m.content for m in session.get_messages() if m.role == "user"]
        calls.append((run_input.input_content, previous))
        return f"Evidence for {run_input.input_content}; previous={previous}"

    async def aresolve(run_input, session, agent, run_context):
        return resolve(run_input, session, agent, run_context)

    def attach(run_input, session, run_context):
        previous = [m.content for m in session.get_messages() if m.role == "user"]
        run_context.dependencies = {"docs_context": f"Evidence for {run_input.input_content}; previous={previous}"}

    def check_resolved(run_context):
        assert isinstance(run_context.dependencies["docs_context"], str)

    dependency_model, hook_model = RecordingModel(), RecordingModel()
    dependency_followup = RecordingModel('{"suggestions": ["Next?"]}')
    hook_followup = RecordingModel('{"suggestions": ["Next?"]}')
    options = dict(
        instructions="<search_results>{docs_context}</search_results>",
        add_history_to_context=True,
        followups=True,
        num_followups=1,
        telemetry=False,
    )
    dependency_agent = Agent(
        model=dependency_model,
        followup_model=dependency_followup,
        db=InMemoryDb(),
        dependencies={"docs_context": aresolve if async_mode else resolve},
        pre_hooks=[check_resolved],
        **options,
    )
    hook_agent = Agent(
        model=hook_model,
        followup_model=hook_followup,
        db=InMemoryDb(),
        pre_hooks=[attach],
        **options,
    )
    assert dependency_agent.add_dependencies_to_context is False
    for question in ("first", "second"):
        dependency_result = await _execute(
            dependency_agent,
            async_mode=async_mode,
            stream=stream,
            input=question,
            session_id="test-session",
        )
        hook_result = await _execute(
            hook_agent,
            async_mode=async_mode,
            stream=stream,
            input=question,
            session_id="test-session",
        )
        assert dependency_result.followups == hook_result.followups == ["Next?"]
    assert calls == [("first", []), ("second", ["first"])]
    assert dependency_model.calls == hook_model.calls
    assert dependency_followup.calls == hook_followup.calls
    assert len(dependency_model.calls) == len(dependency_followup.calls) == 2
    assert callable(dependency_agent.dependencies["docs_context"])


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_dependency_input_is_not_retrieved_again_on_model_retry(async_mode, stream):
    calls = []

    def resolve(run_input, session):
        calls.append((run_input.input_content, session.session_id))
        return "retrieved evidence"

    async def aresolve(run_input, session):
        return resolve(run_input, session)

    model = RecordingModel(fail_first=True)
    agent = Agent(
        model=model,
        dependencies={"evidence": aresolve if async_mode else resolve},
        instructions="Evidence: {evidence}",
        retries=1,
        delay_between_retries=0,
        telemetry=False,
    )
    response = await _execute(agent, async_mode=async_mode, stream=stream, input="question", session_id="s")
    assert response.content == "ok"
    assert calls == [("question", "s")]
    assert len(model.calls) == 2
    assert model.calls[0] == model.calls[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("by_id", [False, True])
async def test_continued_dependency_receives_original_input_and_session(async_mode, stream, by_id):
    calls = []

    def resolve(run_input, session):
        calls.append((run_input.input_content, session.session_id))
        return "resolved"

    async def aresolve(run_input, session):
        return resolve(run_input, session)

    agent = Agent(model=RecordingModel(), db=InMemoryDb(), telemetry=False)
    original = await _execute(agent, async_mode=async_mode, stream=False, input="original", session_id="s")
    kwargs = {"run_id": original.run_id} if by_id else {"run_response": original}
    result = await _execute(
        agent,
        async_mode=async_mode,
        stream=stream,
        continuing=True,
        session_id="s",
        input="extra instruction",
        dependencies={"evidence": aresolve if async_mode else resolve},
        **kwargs,
    )
    assert result.content == "ok"
    assert calls == [("original", "s")]


@pytest.mark.asyncio
async def test_concurrent_dependency_inputs_are_run_local():
    import asyncio

    entered = []
    both_entered = asyncio.Event()

    async def resolve(run_input, session):
        entered.append(run_input.input_content)
        if len(entered) == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=2)
        return f"{session.session_id}:{run_input.input_content}"

    agent = Agent(model=RecordingModel(), dependencies={"x": resolve}, instructions="X={x}", telemetry=False)
    first, second = await asyncio.gather(agent.arun("first", session_id="one"), agent.arun("second", session_id="two"))
    assert "X=one:first" in _system_content(first)
    assert "X=two:second" in _system_content(second)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_continuation_dependencies_follow_persisted_state(tmp_path, async_mode, stream):
    from agno.db.sqlite import SqliteDb

    path = str(tmp_path / "agent.db")
    original_agent = Agent(id="persistent", model=RecordingModel(), db=SqliteDb(db_file=path), telemetry=False)
    original = original_agent.run(
        "original", session_id="session", session_state={"published": "old"}, metadata={"tag": "original"}
    )
    calls = []

    def dependency(run_input, session, run_context):
        calls.append(run_input.input_content)
        assert session.session_id == run_context.session_id == "session"
        assert run_context.session_state["published"] == "old"
        assert run_context.metadata["tag"] == "override"
        return "evidence"

    fresh = Agent(id="persistent", model=RecordingModel(), db=SqliteDb(db_file=path), telemetry=False)
    result = await _execute(
        fresh,
        async_mode=async_mode,
        stream=stream,
        continuing=True,
        run_id=original.run_id,
        session_id="session",
        input="supplement",
        metadata={"tag": "override"},
        dependencies={"evidence": dependency},
    )
    assert result.content == "ok" and calls == ["original"]
    stored = Agent(id="persistent", db=SqliteDb(db_file=path), telemetry=False).get_session(session_id="session")
    assert len(stored.runs) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_invalid_continuation_does_not_resolve_dependencies(async_mode, stream, cancelled):
    from agno.exceptions import RunNotContinuableError, RunNotFoundError
    from agno.run.base import RunStatus

    calls = []

    def dependency():
        calls.append(1)
        return "side effect"

    agent = Agent(model=RecordingModel(), db=InMemoryDb(), telemetry=False)
    kwargs = {"run_id": "missing", "session_id": "session"}
    if cancelled:
        original = agent.run("original", session_id="session")
        original.status = RunStatus.cancelled
        kwargs = {"run_response": original}
    with pytest.raises(RunNotContinuableError if cancelled else RunNotFoundError):
        await _execute(
            agent,
            async_mode=async_mode,
            stream=stream,
            continuing=True,
            dependencies={"evidence": dependency},
            **kwargs,
        )
    assert calls == []
