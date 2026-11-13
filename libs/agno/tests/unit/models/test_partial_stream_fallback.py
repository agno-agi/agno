from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import ContextWindowExceededError, ModelProviderError
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.fallback import FallbackConfig, acall_model_stream_with_fallback, call_model_stream_with_fallback
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.team import Team


def scripted(events, error=None):
    def stream(**kwargs):
        yield from events
        if error is not None:
            raise error

    async def astream(**kwargs):
        for event in stream(**kwargs):
            yield event

    return SimpleNamespace(id="scripted", response_stream=stream, aresponse_stream=astream)


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize(
    "event",
    [
        ModelResponse(content="partial"),
        ModelResponse(reasoning_content="partial reasoning"),
        ModelResponse(redacted_reasoning_content="redacted"),
        ModelResponse(parsed={"answer": 0}),
        ModelResponse(event=ModelResponseEvent.tool_call_started.value),
    ],
)
@pytest.mark.parametrize("stage", ["primary", "fallback", "overflow_retry"])
async def test_visible_stream_is_never_replaced(event, stage, async_mode):
    failure = ModelProviderError("partial response failed", status_code=503)
    partial = scripted([event], failure)
    backup = scripted([ModelResponse(content="backup")])
    config = FallbackConfig(on_error=[backup], callback=Mock())
    recovery = None
    if stage == "fallback":
        primary = scripted([], ModelProviderError("unavailable", status_code=503))
        config.on_error = [partial, backup]
    elif stage == "overflow_retry":
        overflow = scripted([], ContextWindowExceededError("too long"))
        primary = SimpleNamespace(id="primary")
        sync_attempts = iter([overflow.response_stream, partial.response_stream])
        async_attempts = iter([overflow.aresponse_stream, partial.aresponse_stream])
        primary.response_stream = lambda **kwargs: next(sync_attempts)(**kwargs)
        primary.aresponse_stream = lambda **kwargs: next(async_attempts)(**kwargs)
        recovery = lambda: True
    else:
        primary = partial
    observed = []
    with pytest.raises(ModelProviderError, match="partial response failed"):
        if async_mode:
            async for item in acall_model_stream_with_fallback(primary, config, recover_from_overflow=recovery):
                observed.append(item)
        else:
            observed.extend(call_model_stream_with_fallback(primary, config, recover_from_overflow=recovery))
    assert event in observed
    assert all(item.content != "backup" for item in observed)
    config.callback.assert_not_called()


class OfflineModel(Model):
    def __init__(self, model_id, mode="healthy", reasoning=False):
        super().__init__(id=model_id, name=model_id, provider="test", retries=0)
        self.mode, self.reasoning = mode, reasoning

    def invoke(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs):
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs):
        if self.mode != "before_output":
            fields = {"reasoning_content": "thinking"} if self.reasoning else {"content": self.id}
            yield ModelResponse(role="assistant", response_usage=MessageMetrics(), **fields)
        if self.mode != "healthy":
            raise ModelProviderError("synthetic failure", status_code=503)

    async def ainvoke_stream(self, *args, **kwargs):
        for event in self.invoke_stream(*args, **kwargs):
            yield event

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.mark.parametrize("runner_type", [Agent, Team])
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("mode,reasoning", [("partial", False), ("partial", True), ("healthy", False), ("before_output", False)])
async def test_stream_and_persisted_run_agree(tmp_path, runner_type, async_mode, mode, reasoning):
    path = str(tmp_path / "runs.db")
    db = SqliteDb(db_file=path)
    kwargs = {"members": []} if runner_type is Team else {}
    runner = runner_type(
        model=OfflineModel("primary", mode, reasoning),
        fallback_models=[OfflineModel("backup")],
        db=db,
        session_id="session",
        retries=0,
        telemetry=False,
        **kwargs,
    )
    if async_mode:
        events = [event async for event in runner.arun("sample", stream=True, stream_events=True)]
    else:
        events = list(runner.run("sample", stream=True, stream_events=True))
    prefix = "Team" if runner_type is Team else ""
    content = "".join(event.content or "" for event in events if event.event == prefix + "RunContent")
    db.db_engine.dispose()
    reopened = SqliteDb(db_file=path)
    try:
        stored = reopened.get_session("session").runs[-1]
        if mode == "partial":
            assert any(event.event == prefix + "RunError" for event in events)
            assert not any(event.event == prefix + "RunCompleted" for event in events)
            assert stored.status.value == "ERROR"
            if reasoning:
                assert stored.reasoning_content == "thinking"
                assert content == ""
            else:
                assert stored.content == content == "primary"
        else:
            assert any(event.event == prefix + "RunCompleted" for event in events)
            assert stored.content == content == ("backup" if mode == "before_output" else "primary")
    finally:
        reopened.db_engine.dispose()
