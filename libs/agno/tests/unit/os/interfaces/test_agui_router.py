from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core.types import Tool as AGUITool

from agno.os.interfaces.agui.router import run_entity


class FakeRunInput:
    def __init__(self, *, context=None, state=None, tools=None, messages=None):
        self.messages = messages if messages is not None else [MagicMock(role="user", content="test")]
        self.thread_id = "test-thread"
        self.run_id = "test-run"
        self.forwarded_props = None
        self.state = state
        self.context = context
        self.tools = tools


class CaptureKwargsEntity:
    def __init__(self):
        self.captured_kwargs = {}
        self.dependencies = None
        self.arun_called = False
        self.acontinue_run_called = False

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        self.arun_called = True
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
async def test_run_entity_no_context_omits_add_dependencies_flag():
    """No context means no add_dependencies_to_context passed."""
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput(context=None)

    async for _ in run_entity(fake_entity, run_input):
        pass

    assert "add_dependencies_to_context" not in fake_entity.captured_kwargs


@pytest.mark.asyncio
async def test_run_entity_with_context_passes_run_context_with_dependencies():
    """Context items are passed via run_context.dependencies with add_dependencies_to_context=True."""
    fake_entity = CaptureKwargsEntity()
    context = [MagicMock(description="user_name", value="Alice")]
    run_input = FakeRunInput(context=context)

    async for _ in run_entity(fake_entity, run_input):
        pass

    assert fake_entity.captured_kwargs.get("add_dependencies_to_context") is True
    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context is not None
    assert run_context.dependencies == {"user_name": "Alice"}


@pytest.mark.asyncio
async def test_run_entity_passes_client_tools_in_run_context():
    fake_entity = CaptureKwargsEntity()
    agui_tools = [
        AGUITool(name="change_background", description="Change page background color"),
        AGUITool(name="show_modal", description="Show a modal dialog"),
    ]
    run_input = FakeRunInput(tools=agui_tools)

    async for _ in run_entity(fake_entity, run_input):
        pass

    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context is not None
    assert run_context.client_tools is not None
    assert len(run_context.client_tools) == 2

    tool_names = [t.name for t in run_context.client_tools]
    assert "change_background" in tool_names
    assert "show_modal" in tool_names

    for tool in run_context.client_tools:
        assert tool.external_execution is True
        assert tool.external_execution_silent is True


@pytest.mark.asyncio
async def test_run_entity_no_client_tools_when_tools_none():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput(tools=None)

    async for _ in run_entity(fake_entity, run_input):
        pass

    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context is not None
    assert run_context.client_tools is None


@pytest.mark.asyncio
async def test_run_entity_no_client_tools_when_tools_empty():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput(tools=[])

    async for _ in run_entity(fake_entity, run_input):
        pass

    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context is not None
    assert run_context.client_tools is None


@pytest.mark.asyncio
async def test_run_entity_passes_user_id_to_arun():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput()

    async for _ in run_entity(fake_entity, run_input, user_id="test-user-123"):
        pass

    assert fake_entity.captured_kwargs.get("user_id") == "test-user-123"
    run_context = fake_entity.captured_kwargs.get("run_context")
    assert run_context.user_id == "test-user-123"


@pytest.mark.asyncio
async def test_run_entity_fresh_run_calls_arun():
    fake_entity = CaptureKwargsEntity()
    run_input = FakeRunInput()

    async for _ in run_entity(fake_entity, run_input):
        pass

    assert fake_entity.arun_called is True
