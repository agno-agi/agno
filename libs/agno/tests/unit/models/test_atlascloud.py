import json

import httpx
import pytest

from agno.exceptions import ModelAuthenticationError, ModelProviderError
from agno.models.atlascloud import AtlasCloud
from agno.models.message import Message
from agno.models.utils import get_model, get_model_from_dict


def test_defaults():
    model = AtlasCloud()
    assert model.id == "deepseek-ai/deepseek-v3.2"
    assert model.provider == "AtlasCloud"
    assert model.base_url == "https://api.atlascloud.ai/v1"
    assert model.max_retries == 0
    assert model.retries == 0


def test_environment_key(monkeypatch):
    monkeypatch.setenv("ATLASCLOUD_API_KEY", "atlas-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-test-key")
    assert AtlasCloud()._get_client_params()["api_key"] == "atlas-test-key"


def test_explicit_key_and_client_options(monkeypatch):
    monkeypatch.setenv("ATLASCLOUD_API_KEY", "env-test-key")
    params = AtlasCloud(api_key="explicit-test-key", timeout=20)._get_client_params()
    assert params["api_key"] == "explicit-test-key"
    assert params["timeout"] == 20
    assert params["max_retries"] == 0


@pytest.mark.parametrize("key", [None, ""])
def test_missing_atlas_key_never_uses_openai_key(monkeypatch, key):
    monkeypatch.delenv("ATLASCLOUD_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-test-key")
    with pytest.raises(ModelAuthenticationError, match="ATLASCLOUD_API_KEY"):
        AtlasCloud(api_key=key)._get_client_params()


@pytest.mark.parametrize("model_id", ["deepseek-ai/deepseek-v3.2", "openai/gpt-4.1-mini"])
def test_string_construction_and_serialization(model_id):
    model = get_model(f"atlascloud:{model_id}")
    assert isinstance(model, AtlasCloud)
    assert model.id == model_id
    restored = get_model_from_dict(model.to_dict())
    assert isinstance(restored, AtlasCloud)
    assert restored.id == model_id


def completion_response(request):
    assert str(request.url) == "https://api.atlascloud.ai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer atlas-test-key"
    body = json.loads(request.content)
    assert body["model"] == "deepseek-ai/deepseek-v3.2"
    assert body["messages"][0] == {"role": "system", "content": "Be concise."}
    assert body["messages"][1] == {"role": "user", "content": "Hello"}
    return httpx.Response(
        200,
        json={
            "id": "test-completion",
            "object": "chat.completion",
            "created": 0,
            "model": body["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
        },
    )


def test_sync_completion_transport():
    with httpx.Client(transport=httpx.MockTransport(completion_response)) as client:
        model = AtlasCloud(api_key="atlas-test-key", http_client=client)
        response = model.invoke(
            [Message(role="system", content="Be concise."), Message(role="user", content="Hello")],
            assistant_message=Message(role="assistant"),
        )
        assert response.content == "Hello!"


@pytest.mark.asyncio
async def test_async_completion_transport():
    async with httpx.AsyncClient(transport=httpx.MockTransport(completion_response)) as client:
        model = AtlasCloud(api_key="atlas-test-key", http_client=client)
        response = await model.ainvoke(
            [Message(role="system", content="Be concise."), Message(role="user", content="Hello")],
            assistant_message=Message(role="assistant"),
        )
        assert response.content == "Hello!"


def test_failed_generation_is_not_retried():
    requests = []

    def fail(request):
        requests.append(request)
        return httpx.Response(500, json={"error": {"message": "test failure"}})

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        model = AtlasCloud(api_key="atlas-test-key", http_client=client)
        with pytest.raises(ModelProviderError):
            model.invoke([Message(role="user", content="Hello")], assistant_message=Message(role="assistant"))
    assert len(requests) == 1
