"""Preserve MCP Host fields on ToolExecution (issue #9087).

ToolResult.metadata already carries structured_content / meta. These must reach
ToolExecution (for run persistence) and AG-UI TOOL_CALL_RESULT (for live hosts)
without being merged into the model-visible result string.
"""

from ag_ui.core import EventType

from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponseEvent, ToolExecution
from agno.os.interfaces.agui.handlers import on_tool_call_completed
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import ToolCallCompletedEvent
from agno.tools.function import Function, FunctionCall, ToolResult


class TestToolExecutionHostFieldsRoundTrip:
    def test_to_dict_from_dict_preserves_host_fields(self):
        original = ToolExecution(
            tool_call_id="call-1",
            tool_name="show_map",
            result="Map ready",
            structured_content={"center": {"lat": 1.0, "lng": 2.0}},
            meta={"ui": {"resourceUri": "ui://maps/widget"}},
        )
        restored = ToolExecution.from_dict(original.to_dict())

        assert restored.result == "Map ready"
        assert restored.structured_content == {"center": {"lat": 1.0, "lng": 2.0}}
        assert restored.meta == {"ui": {"resourceUri": "ui://maps/widget"}}

    def test_from_dict_without_host_fields_defaults_to_none(self):
        restored = ToolExecution.from_dict({"tool_name": "echo", "result": "hi"})
        assert restored.structured_content is None
        assert restored.meta is None


class TestToolResultMetadataPropagatesToToolExecution:
    def test_sync_run_function_call_lifts_host_fields(self):
        def map_tool() -> ToolResult:
            return ToolResult(
                content="Map ready",
                metadata={
                    "structured_content": {"ok": True},
                    "meta": {"ui": {"resourceUri": "ui://maps/widget"}},
                },
            )

        func = Function.from_callable(map_tool)
        func.process_entrypoint()
        fc = FunctionCall(function=func, arguments={}, call_id="call-map")

        model = OpenAIChat(id="gpt-4o")
        completed = None
        for event in model.run_function_call(fc, function_call_results=[]):
            if getattr(event, "event", None) == ModelResponseEvent.tool_call_completed.value:
                completed = event

        assert completed is not None
        assert completed.tool_executions is not None
        tool = completed.tool_executions[0]
        assert tool.result == "Map ready"
        assert tool.structured_content == {"ok": True}
        assert tool.meta == {"ui": {"resourceUri": "ui://maps/widget"}}

    def test_sync_run_function_call_without_metadata_leaves_host_fields_none(self):
        def plain_tool() -> ToolResult:
            return ToolResult(content="done")

        func = Function.from_callable(plain_tool)
        func.process_entrypoint()
        fc = FunctionCall(function=func, arguments={}, call_id="call-plain")

        model = OpenAIChat(id="gpt-4o")
        completed = None
        for event in model.run_function_call(fc, function_call_results=[]):
            if getattr(event, "event", None) == ModelResponseEvent.tool_call_completed.value:
                completed = event

        assert completed is not None
        tool = completed.tool_executions[0]
        assert tool.result == "done"
        assert tool.structured_content is None
        assert tool.meta is None


class TestAguiForwardsHostFields:
    def test_tool_call_result_includes_structured_content_and_meta(self):
        tool = ToolExecution(
            tool_call_id="call-1",
            tool_name="show_map",
            result="Map ready",
            structured_content={"ok": True},
            meta={"ui": {"resourceUri": "ui://maps/widget"}},
        )
        chunk = ToolCallCompletedEvent()
        chunk.tool = tool

        state = StreamState()
        state.start_tool_call("call-1")
        events = on_tool_call_completed(chunk, state)

        result_events = [e for e in events if e.type == EventType.TOOL_CALL_RESULT]
        assert len(result_events) == 1
        event = result_events[0]
        assert event.content == '"Map ready"'
        assert event.model_extra.get("structuredContent") == {"ok": True}
        assert event.model_extra.get("_meta") == {"ui": {"resourceUri": "ui://maps/widget"}}

        dumped = event.model_dump(by_alias=True, exclude_none=True)
        assert dumped["content"] == '"Map ready"'
        assert dumped["structuredContent"] == {"ok": True}
        assert dumped["_meta"] == {"ui": {"resourceUri": "ui://maps/widget"}}

    def test_tool_call_result_omits_host_fields_when_absent(self):
        tool = ToolExecution(tool_call_id="call-2", tool_name="echo", result="hi")
        chunk = ToolCallCompletedEvent()
        chunk.tool = tool

        state = StreamState()
        state.start_tool_call("call-2")
        events = on_tool_call_completed(chunk, state)

        result_events = [e for e in events if e.type == EventType.TOOL_CALL_RESULT]
        assert len(result_events) == 1
        dumped = result_events[0].model_dump(by_alias=True, exclude_none=True)
        assert "structuredContent" not in dumped
        assert "_meta" not in dumped
