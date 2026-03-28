"""Unit tests for ModelFeedbackTools class."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.base import RunContext
from agno.tools.model_feedback import ModelFeedbackTools


def _make_run_context(messages=None):
    """Create a RunContext with the given messages."""
    return RunContext(
        run_id="test-run",
        session_id="test-session",
        messages=messages,
    )


def _make_mock_model(model_id="mock-model", content=None):
    """Create a mock Model that returns the given content from invoke/ainvoke."""
    if content is None:
        content = json.dumps(
            {
                "overall_rating": 8,
                "aspects": {
                    "accuracy": {"rating": 9, "comment": "Factually correct"},
                },
                "suggestions": ["Add more examples"],
                "summary": "Good response overall.",
            }
        )
    model = MagicMock()
    model.id = model_id
    model.name = model_id
    model.invoke.return_value = ModelResponse(content=content)
    model.ainvoke = AsyncMock(return_value=ModelResponse(content=content))
    return model


@pytest.fixture
def mock_model():
    return _make_mock_model()


@pytest.fixture
def feedback_tool(mock_model):
    return ModelFeedbackTools(model=mock_model, aspects=["accuracy"])


@pytest.fixture
def run_context_with_messages():
    return _make_run_context(
        messages=[
            Message(role="user", content="What is Python?"),
            Message(role="assistant", content="Python is a programming language."),
        ]
    )


class TestInitialization:
    def test_default_aspects(self, mock_model):
        tool = ModelFeedbackTools(model=mock_model)
        assert tool.aspects == ["accuracy", "completeness", "clarity"]

    def test_custom_aspects(self, mock_model):
        tool = ModelFeedbackTools(model=mock_model, aspects=["tone", "depth"])
        assert tool.aspects == ["tone", "depth"]

    def test_single_model(self, mock_model):
        tool = ModelFeedbackTools(model=mock_model)
        assert len(tool.feedback_models) == 1
        assert tool.feedback_models[0] is mock_model

    def test_multiple_models(self):
        m1 = _make_mock_model("model-a")
        m2 = _make_mock_model("model-b")
        tool = ModelFeedbackTools(models=[m1, m2])
        assert len(tool.feedback_models) == 2

    def test_models_param_takes_precedence(self):
        single = _make_mock_model("single")
        m1 = _make_mock_model("model-a")
        m2 = _make_mock_model("model-b")
        tool = ModelFeedbackTools(model=single, models=[m1, m2])
        assert len(tool.feedback_models) == 2
        assert single not in tool.feedback_models

    def test_default_gemini_lazy(self):
        tool = ModelFeedbackTools()
        assert tool.feedback_models == []

    def test_toolkit_name(self, mock_model):
        tool = ModelFeedbackTools(model=mock_model)
        assert tool.name == "model_feedback_tools"


class TestToolRegistration:
    def test_sync_function_registered(self, feedback_tool):
        function_names = list(feedback_tool.functions.keys())
        assert "get_feedback" in function_names

    def test_async_function_registered(self, feedback_tool):
        function_names = list(feedback_tool.async_functions.keys())
        assert "get_feedback" in function_names


class TestConversationFormatting:
    def test_basic_formatting(self, feedback_tool):
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        result = feedback_tool._format_conversation(messages)
        assert "[USER]: Hello" in result
        assert "[ASSISTANT]: Hi there" in result

    def test_excludes_system_by_default(self, feedback_tool):
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        result = feedback_tool._format_conversation(messages)
        assert "SYSTEM" not in result
        assert "[USER]: Hello" in result

    def test_includes_system_when_enabled(self, mock_model):
        tool = ModelFeedbackTools(model=mock_model, include_system_messages=True)
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        result = tool._format_conversation(messages)
        assert "[SYSTEM]: You are helpful" in result

    def test_max_messages_limit(self, mock_model):
        tool = ModelFeedbackTools(model=mock_model, max_messages=2)
        messages = [
            Message(role="user", content="First"),
            Message(role="assistant", content="Response 1"),
            Message(role="user", content="Second"),
            Message(role="assistant", content="Response 2"),
        ]
        result = tool._format_conversation(messages)
        assert "First" not in result
        assert "Response 2" in result

    def test_skips_tool_messages(self, feedback_tool):
        messages = [
            Message(role="user", content="Hello"),
            Message(role="tool", content="tool result"),
            Message(role="assistant", content="Response"),
        ]
        result = feedback_tool._format_conversation(messages)
        assert "tool result" not in result

    def test_skips_empty_content(self, feedback_tool):
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content=None),
        ]
        result = feedback_tool._format_conversation(messages)
        assert "ASSISTANT" not in result


class TestSystemPrompt:
    def test_default_prompt_includes_aspects(self, feedback_tool):
        prompt = feedback_tool._build_system_prompt()
        assert "accuracy" in prompt

    def test_prompt_includes_focus(self, feedback_tool):
        prompt = feedback_tool._build_system_prompt(focus="code quality")
        assert "code quality" in prompt

    def test_custom_system_prompt(self, mock_model):
        tool = ModelFeedbackTools(
            model=mock_model,
            system_prompt="You are a code reviewer.",
        )
        prompt = tool._build_system_prompt()
        assert prompt == "You are a code reviewer."


class TestGetFeedback:
    def test_single_model_feedback(self, feedback_tool, mock_model, run_context_with_messages):
        result = feedback_tool.get_feedback(run_context=run_context_with_messages)
        result_data = json.loads(result)
        assert "overall_rating" in result_data
        assert result_data["model"] == "mock-model"
        mock_model.invoke.assert_called_once()

    def test_empty_messages(self, feedback_tool):
        ctx = _make_run_context(messages=[])
        result = feedback_tool.get_feedback(run_context=ctx)
        result_data = json.loads(result)
        assert "error" in result_data

    def test_no_messages(self, feedback_tool):
        ctx = _make_run_context(messages=None)
        result = feedback_tool.get_feedback(run_context=ctx)
        result_data = json.loads(result)
        assert "error" in result_data

    def test_multi_model_feedback(self, run_context_with_messages):
        m1 = _make_mock_model("model-a")
        m2 = _make_mock_model("model-b")
        tool = ModelFeedbackTools(models=[m1, m2])
        result = tool.get_feedback(run_context=run_context_with_messages)
        result_data = json.loads(result)
        assert "feedback" in result_data
        assert len(result_data["feedback"]) == 2
        model_ids = {f["model"] for f in result_data["feedback"]}
        assert "model-a" in model_ids
        assert "model-b" in model_ids

    def test_model_error_handling(self, run_context_with_messages):
        model = MagicMock()
        model.id = "failing-model"
        model.name = "failing-model"
        model.invoke.side_effect = Exception("API error")
        tool = ModelFeedbackTools(model=model)
        result = tool.get_feedback(run_context=run_context_with_messages)
        result_data = json.loads(result)
        assert "error" in result_data
        assert "API error" in result_data["error"]

    def test_non_json_model_response(self, run_context_with_messages):
        model = _make_mock_model("raw-model", content="This is plain text feedback.")
        tool = ModelFeedbackTools(model=model)
        result = tool.get_feedback(run_context=run_context_with_messages)
        result_data = json.loads(result)
        assert "raw_feedback" in result_data
        assert result_data["raw_feedback"] == "This is plain text feedback."

    def test_focus_parameter(self, feedback_tool, mock_model, run_context_with_messages):
        feedback_tool.get_feedback(run_context=run_context_with_messages, focus="code quality")
        call_args = mock_model.invoke.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        system_content = messages[0].content
        assert "code quality" in system_content


class TestAsyncGetFeedback:
    @pytest.mark.asyncio
    async def test_single_model_feedback(self, feedback_tool, mock_model, run_context_with_messages):
        result = await feedback_tool.aget_feedback(run_context=run_context_with_messages)
        result_data = json.loads(result)
        assert "overall_rating" in result_data
        assert result_data["model"] == "mock-model"
        mock_model.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_multi_model_feedback(self, run_context_with_messages):
        m1 = _make_mock_model("model-a")
        m2 = _make_mock_model("model-b")
        tool = ModelFeedbackTools(models=[m1, m2])
        result = await tool.aget_feedback(run_context=run_context_with_messages)
        result_data = json.loads(result)
        assert "feedback" in result_data
        assert len(result_data["feedback"]) == 2

    @pytest.mark.asyncio
    async def test_empty_messages(self, feedback_tool):
        ctx = _make_run_context(messages=None)
        result = await feedback_tool.aget_feedback(run_context=ctx)
        result_data = json.loads(result)
        assert "error" in result_data
