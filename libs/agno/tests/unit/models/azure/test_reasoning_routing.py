import pytest

from agno.models.azure import AzureOpenAIResponses
from agno.reasoning.manager import ReasoningConfig, ReasoningManager
from agno.reasoning.openai import is_openai_reasoning_model


@pytest.mark.parametrize(
    "deployment,override,expected",
    [
        ("prod-reasoner", True, True),
        ("gpt-5-deployment", False, False),
        ("prod-reasoner", None, False),
        ("gpt-5-deployment", None, True),
    ],
)
def test_azure_responses_reasoning_override(deployment, override, expected):
    model = AzureOpenAIResponses(id=deployment, is_reasoning_model=override)
    assert is_openai_reasoning_model(model) is expected
    manager = ReasoningManager(ReasoningConfig(reasoning_model=model))
    assert manager.is_native_reasoning_model() is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("deployment,override", [("prod-reasoner", True), ("gpt-5-deployment", False)])
async def test_azure_responses_async_reasoning_override(deployment, override):
    model = AzureOpenAIResponses(id=deployment, is_reasoning_model=override)
    manager = ReasoningManager(ReasoningConfig(reasoning_model=model))
    assert await manager._adetect_model_type(model) == ("openai" if override else None)
