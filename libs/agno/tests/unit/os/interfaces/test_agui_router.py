from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from agno.os.interfaces.agui.router import run_entity


class FakeRunInput:
    def __init__(self, *, context=None, state=None):
        self.messages = [MagicMock(role="user", content="test")]
        self.thread_id = "test-thread"
        self.run_id = "test-run"
        self.forwarded_props = None
        self.state = state
        self.context = context


class CaptureKwargsEntity:
    def __init__(self):
        self.captured_kwargs = {}
        self.dependencies = None

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        return
        yield


@pytest.mark.asyncio
async def test_run_entity_passes_stream_events():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput()

    events = []
    async for event in run_entity(fake_entity, run_input):
        events.append(event)

    assert fake_entity.captured_kwargs.get("stream") is True
    assert fake_entity.captured_kwargs.get("stream_events") is True
    assert "stream_steps" not in fake_entity.captured_kwargs


@pytest.mark.asyncio
async def test_run_entity_no_context_omits_dependencies_kwarg():
    """No context means no dependencies or add_dependencies_to_context passed."""
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput(context=None)

    async for _ in run_entity(fake_entity, run_input):
        pass

    assert "add_dependencies_to_context" not in fake_entity.captured_kwargs
    assert "dependencies" not in fake_entity.captured_kwargs


@pytest.mark.asyncio
async def test_run_entity_with_context_passes_dependencies():
    """Context items are passed as dependencies with add_dependencies_to_context=True."""
    fake_entity = CaptureKwargsEntity()
    context = [MagicMock(description="user_name", value="Alice")]
    run_input = FakeRunInput(context=context)

    async for _ in run_entity(fake_entity, run_input):
        pass

    assert fake_entity.captured_kwargs.get("add_dependencies_to_context") is True
    assert fake_entity.captured_kwargs.get("dependencies") == {"user_name": "Alice"}
