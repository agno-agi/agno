"""Unit tests for AdvisorTools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tools.advisor import DEFAULT_SYSTEM_MESSAGE, AdvisorTools


def _mock_model(model_id: str, provider: str = "MockProvider", content: str = "mock response") -> MagicMock:
    model = MagicMock(spec=Model)
    model.id = model_id
    model.get_provider.return_value = provider
    model.response.return_value = ModelResponse(content=content)
    model.aresponse.return_value = ModelResponse(content=content)
    return model


# ============================================================================
# Initialization
# ============================================================================


def test_init_requires_advisors():
    with pytest.raises(ValueError, match="at least one advisor"):
        AdvisorTools(advisors=[])


def test_init_registers_expected_tools():
    tools = AdvisorTools(advisors=[_mock_model("model-a")])
    assert set(tools.functions.keys()) == {"ask_advisor", "ask_all_advisors"}
    assert set(tools.async_functions.keys()) == {"ask_advisor", "ask_all_advisors"}


def test_init_without_ask_all_advisors():
    tools = AdvisorTools(advisors=[_mock_model("model-a")], ask_all_advisors=False)
    assert set(tools.functions.keys()) == {"ask_advisor"}
    assert set(tools.async_functions.keys()) == {"ask_advisor"}


def test_init_resolves_model_strings():
    resolved = _mock_model("gpt-x")
    with patch("agno.tools.advisor.get_model", return_value=resolved) as mock_get_model:
        tools = AdvisorTools(advisors=["openai:gpt-x"])
    mock_get_model.assert_called_once_with("openai:gpt-x")
    assert tools.advisors == {"gpt-x": resolved}


def test_init_disambiguates_duplicate_ids():
    model_a = _mock_model("same-id", provider="ProviderA")
    model_b = _mock_model("same-id", provider="ProviderB")
    tools = AdvisorTools(advisors=[model_a, model_b])
    assert set(tools.advisors.keys()) == {"same-id", "ProviderB:same-id"}


def test_init_rejects_exact_duplicates():
    model_a = _mock_model("same-id", provider="SameProvider")
    model_b = _mock_model("same-id", provider="SameProvider")
    with pytest.raises(ValueError, match="Duplicate advisor"):
        AdvisorTools(advisors=[model_a, model_b])


def test_instructions_list_advisors_with_descriptions():
    tools = AdvisorTools(
        advisors=[_mock_model("model-a"), _mock_model("model-b")],
        descriptions={"model-a": "Good at math"},
    )
    assert tools.add_instructions is True
    assert "- model-a: Good at math" in tools.instructions
    assert "- model-b" in tools.instructions


# ============================================================================
# ask_advisor
# ============================================================================


def test_ask_advisor_returns_model_content():
    model = _mock_model("model-a", content="the answer")
    tools = AdvisorTools(advisors=[model])
    assert tools.ask_advisor(advisor="model-a", prompt="a question") == "the answer"


def test_ask_advisor_sends_system_and_user_messages():
    model = _mock_model("model-a")
    tools = AdvisorTools(advisors=[model])
    tools.ask_advisor(advisor="model-a", prompt="a question", context="some context")

    messages = model.response.call_args.kwargs["messages"]
    assert [m.role for m in messages] == ["system", "user"]
    assert messages[0].content == DEFAULT_SYSTEM_MESSAGE
    assert "a question" in messages[1].content
    assert "<context>\nsome context\n</context>" in messages[1].content


def test_ask_advisor_without_system_message():
    model = _mock_model("model-a")
    tools = AdvisorTools(advisors=[model], system_message=None)
    tools.ask_advisor(advisor="model-a", prompt="a question")

    messages = model.response.call_args.kwargs["messages"]
    assert [m.role for m in messages] == ["user"]


def test_ask_advisor_unknown_advisor_lists_available():
    tools = AdvisorTools(advisors=[_mock_model("model-a"), _mock_model("model-b")])
    result = tools.ask_advisor(advisor="nope", prompt="a question")
    assert "unknown advisor 'nope'" in result
    assert "model-a" in result
    assert "model-b" in result


def test_ask_advisor_handles_model_error():
    model = _mock_model("model-a")
    model.response.side_effect = RuntimeError("boom")
    tools = AdvisorTools(advisors=[model])
    result = tools.ask_advisor(advisor="model-a", prompt="a question")
    assert "Error asking advisor 'model-a'" in result
    assert "boom" in result


def test_ask_advisor_handles_none_content():
    model = _mock_model("model-a")
    model.response.return_value = ModelResponse(content=None)
    tools = AdvisorTools(advisors=[model])
    assert tools.ask_advisor(advisor="model-a", prompt="a question") == ""


async def test_aask_advisor_returns_model_content():
    model = _mock_model("model-a", content="the async answer")
    tools = AdvisorTools(advisors=[model])
    assert await tools.aask_advisor(advisor="model-a", prompt="a question") == "the async answer"
    model.aresponse.assert_awaited_once()


async def test_aask_advisor_unknown_advisor_lists_available():
    tools = AdvisorTools(advisors=[_mock_model("model-a")])
    result = await tools.aask_advisor(advisor="nope", prompt="a question")
    assert "unknown advisor 'nope'" in result
    assert "model-a" in result


async def test_aask_advisor_handles_model_error():
    model = _mock_model("model-a")
    model.aresponse.side_effect = RuntimeError("boom")
    tools = AdvisorTools(advisors=[model])
    result = await tools.aask_advisor(advisor="model-a", prompt="a question")
    assert "Error asking advisor 'model-a'" in result


# ============================================================================
# ask_all_advisors
# ============================================================================


def test_ask_all_advisors_returns_all_responses():
    model_a = _mock_model("model-a", content="answer a")
    model_b = _mock_model("model-b", content="answer b")
    tools = AdvisorTools(advisors=[model_a, model_b])

    results = json.loads(tools.ask_all_advisors(prompt="a question"))
    assert results == {"model-a": "answer a", "model-b": "answer b"}


def test_ask_all_advisors_includes_per_advisor_errors():
    model_a = _mock_model("model-a", content="answer a")
    model_b = _mock_model("model-b")
    model_b.response.side_effect = RuntimeError("boom")
    tools = AdvisorTools(advisors=[model_a, model_b])

    results = json.loads(tools.ask_all_advisors(prompt="a question"))
    assert results["model-a"] == "answer a"
    assert "Error asking advisor 'model-b'" in results["model-b"]


async def test_aask_all_advisors_returns_all_responses():
    model_a = _mock_model("model-a", content="answer a")
    model_b = _mock_model("model-b", content="answer b")
    tools = AdvisorTools(advisors=[model_a, model_b])

    results = json.loads(await tools.aask_all_advisors(prompt="a question"))
    assert results == {"model-a": "answer a", "model-b": "answer b"}
