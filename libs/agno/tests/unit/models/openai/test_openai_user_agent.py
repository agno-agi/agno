from platform import python_version

import httpx
import pytest

from agno import __version__
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIChat
from agno.models.openai.like import OpenAILike

DEFAULT_USER_AGENT = f"agno/{__version__} Python/{python_version()}"


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    ("model_class", "env_user_agent", "options", "expected_user_agent", "expected_header"),
    [
        pytest.param(OpenAILike, None, {}, DEFAULT_USER_AGENT, None, id="default"),
        pytest.param(OpenAILike, "env-agent", {}, "env-agent", None, id="env-override"),
        pytest.param(
            OpenAILike,
            None,
            {"default_headers": {"X-Provider-Header": "model"}},
            DEFAULT_USER_AGENT,
            "model",
            id="preserve-default-headers",
        ),
        pytest.param(
            OpenAILike,
            "env-agent",
            {"default_headers": {"user-agent": "model-agent", "X-Provider-Header": "model"}},
            "model-agent",
            "model",
            id="caller-header",
        ),
        pytest.param(
            OpenAILike,
            "env-agent",
            {
                "default_headers": {"User-Agent": "model-agent", "X-Provider-Header": "model"},
                "client_params": {"default_headers": {"uSeR-aGeNt": "client-agent", "X-Provider-Header": "client"}},
            },
            "client-agent",
            "client",
            id="client-params-precedence",
        ),
        pytest.param(DeepSeek, None, {}, DEFAULT_USER_AGENT, None, id="provider-with-custom-client-params"),
        pytest.param(OpenAIChat, "env-agent", {}, None, None, id="native-openai"),
    ],
)
async def test_openai_user_agent_on_request(
    monkeypatch, use_async, model_class, env_user_agent, options, expected_user_agent, expected_header
):
    if env_user_agent is None:
        monkeypatch.delenv("AGNO_USER_AGENT", raising=False)
    else:
        monkeypatch.setenv("AGNO_USER_AGENT", env_user_agent)

    requests = []

    def capture(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [], "object": "list"})

    model = model_class(id="test-model", api_key="test-key", base_url="https://example.test/v1", **options)
    transport = httpx.MockTransport(capture)
    if use_async:
        async with httpx.AsyncClient(transport=transport) as http_client:
            model.http_client = http_client
            client = model.get_async_client()
            await client.models.list()
    else:
        with httpx.Client(transport=transport) as http_client:
            model.http_client = http_client
            client = model.get_client()
            client.models.list()

    (request,) = requests
    assert request.headers.get_list("user-agent") == [expected_user_agent or client.user_agent]
    assert request.headers.get("x-provider-header") == expected_header
