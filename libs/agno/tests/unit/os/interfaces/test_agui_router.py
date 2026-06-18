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


# ---------------------------------------------------------------------------
# AG-UI readable context flow (PR for issue #7805)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_entity_no_context_omits_add_dependencies_to_context_kwarg():
    """When no AGUI context is sent, the kwarg should NOT be passed —
    preserves the entity's own `add_dependencies_to_context` configuration.
    """
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput(context=None)

    events = []
    async for event in run_entity(fake_entity, run_input):
        events.append(event)

    assert "add_dependencies_to_context" not in fake_entity.captured_kwargs
    assert "dependencies" not in fake_entity.captured_kwargs


@pytest.mark.asyncio
async def test_run_entity_with_context_passes_ui_deps():
    """When AGUI context is present, UI deps are passed to arun().
    SDK handles merging with entity.dependencies internally."""
    fake_entity = CaptureKwargsEntity()
    fake_entity.dependencies = {"existing_dep": "preserved"}
    context = [MagicMock(description="user_name", value="Alice")]
    run_input = FakeRunInput(context=context)

    events = []
    async for event in run_entity(fake_entity, run_input):
        events.append(event)

    assert fake_entity.captured_kwargs.get("add_dependencies_to_context") is True
    deps = fake_entity.captured_kwargs.get("dependencies")
    assert deps == {"user_name": "Alice"}
    # session_state must remain untouched (no agui_context pollution)
    session_state = fake_entity.captured_kwargs.get("session_state")
    assert session_state is None or "agui_context" not in session_state
