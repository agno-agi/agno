import pytest

from agno.models.openai import OpenAIChat
from agno.tools.function import Function, FunctionCall


class TestDelegateMemberAttribution:
    @pytest.fixture
    def model(self):
        return OpenAIChat(id="gpt-5-mini")

    @pytest.fixture
    def delegate_function(self):
        def delegate_task_to_member(member_id: str, task: str) -> str:
            return "Mock response"

        return Function.from_callable(delegate_task_to_member)

    @pytest.fixture
    def regular_function(self):
        def get_weather(city: str) -> str:
            return "Sunny"

        return Function.from_callable(get_weather)

    def test_delegate_result_prefixed_with_member_id(self, model, delegate_function):
        function_call = FunctionCall(
            call_id="call_123",
            function=delegate_function,
            arguments={"member_id": "analyst-agent", "task": "Analyze the data"},
        )

        result = model.create_function_call_result(
            function_call=function_call,
            success=True,
            output="The analysis shows positive trends.",
        )

        assert result.content == "[analyst-agent]: The analysis shows positive trends."
        assert result.role == "tool"
        assert result.tool_name == "delegate_task_to_member"

    def test_delegate_result_not_double_prefixed(self, model, delegate_function):
        function_call = FunctionCall(
            call_id="call_123",
            function=delegate_function,
            arguments={"member_id": "analyst-agent", "task": "Analyze the data"},
        )

        result = model.create_function_call_result(
            function_call=function_call,
            success=True,
            output="[analyst-agent]: Already prefixed content",
        )

        assert result.content == "[analyst-agent]: Already prefixed content"

    def test_delegate_result_handles_whitespace_prefix(self, model, delegate_function):
        function_call = FunctionCall(
            call_id="call_123",
            function=delegate_function,
            arguments={"member_id": "analyst-agent", "task": "Analyze the data"},
        )

        result = model.create_function_call_result(
            function_call=function_call,
            success=True,
            output="  [analyst-agent]: Content with leading spaces",
        )

        assert result.content == "  [analyst-agent]: Content with leading spaces"

    def test_delegate_result_error_not_prefixed(self, model, delegate_function):
        function_call = FunctionCall(
            call_id="call_123",
            function=delegate_function,
            arguments={"member_id": "analyst-agent", "task": "Analyze the data"},
        )
        function_call.error = "Member not found"

        result = model.create_function_call_result(
            function_call=function_call,
            success=False,
            output="Some output that should be ignored",
        )

        assert result.content == "Member not found"
        assert result.tool_call_error is True

    def test_delegate_result_empty_output_not_prefixed(self, model, delegate_function):
        function_call = FunctionCall(
            call_id="call_123",
            function=delegate_function,
            arguments={"member_id": "analyst-agent", "task": "Analyze the data"},
        )

        result = model.create_function_call_result(
            function_call=function_call,
            success=True,
            output="",
        )

        assert result.content == ""

    def test_delegate_result_none_output_not_prefixed(self, model, delegate_function):
        function_call = FunctionCall(
            call_id="call_123",
            function=delegate_function,
            arguments={"member_id": "analyst-agent", "task": "Analyze the data"},
        )

        result = model.create_function_call_result(
            function_call=function_call,
            success=True,
            output=None,
        )

        assert result.content is None

    def test_delegate_result_missing_member_id_not_prefixed(self, model, delegate_function):
        function_call = FunctionCall(
            call_id="call_123",
            function=delegate_function,
            arguments={"task": "Analyze the data"},
        )

        result = model.create_function_call_result(
            function_call=function_call,
            success=True,
            output="The analysis shows positive trends.",
        )

        assert result.content == "The analysis shows positive trends."

    def test_regular_tool_result_not_prefixed(self, model, regular_function):
        function_call = FunctionCall(
            call_id="call_456",
            function=regular_function,
            arguments={"city": "Tokyo"},
        )

        result = model.create_function_call_result(
            function_call=function_call,
            success=True,
            output="Sunny, 25 degrees",
        )

        assert result.content == "Sunny, 25 degrees"
        assert result.tool_name == "get_weather"

    def test_delegate_result_list_output_not_prefixed(self, model, delegate_function):
        function_call = FunctionCall(
            call_id="call_123",
            function=delegate_function,
            arguments={"member_id": "analyst-agent", "task": "Analyze the data"},
        )

        result = model.create_function_call_result(
            function_call=function_call,
            success=True,
            output=["item1", "item2"],
        )

        assert result.content == ["item1", "item2"]

    def test_delegate_result_preserves_tool_args(self, model, delegate_function):
        function_call = FunctionCall(
            call_id="call_123",
            function=delegate_function,
            arguments={"member_id": "analyst-agent", "task": "Analyze the data"},
        )

        result = model.create_function_call_result(
            function_call=function_call,
            success=True,
            output="Analysis complete.",
        )

        assert result.tool_args == {"member_id": "analyst-agent", "task": "Analyze the data"}
        assert result.tool_call_id == "call_123"
