from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.agent_guild import AgentGuildTools


def _success(payload):
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_default_tools_are_read_only_and_have_async_equivalents():
    tools = AgentGuildTools()

    assert tools.name == "agent_guild_tools"
    assert set(tools.functions) == {"check_agent", "list_capabilities", "get_passport", "verify_passport"}
    assert set(tools.async_functions) == set(tools.functions)
    assert "register_agent" not in tools.functions
    assert "request_trial" not in tools.functions


def test_state_creating_tools_require_explicit_opt_in():
    tools = AgentGuildTools(enable_register_agent=True, enable_request_trial=True)

    assert "register_agent" in tools.functions
    assert "request_trial" in tools.functions
    assert set(tools.async_functions) == set(tools.functions)


def test_all_enables_every_tool():
    tools = AgentGuildTools(
        enable_check_agent=False,
        enable_list_capabilities=False,
        enable_get_passport=False,
        enable_verify_passport=False,
        all=True,
    )

    assert set(tools.functions) == {
        "check_agent",
        "list_capabilities",
        "get_passport",
        "verify_passport",
        "register_agent",
        "request_trial",
    }


def test_api_key_uses_environment():
    with patch.dict("os.environ", {"AGENT_GUILD_API_KEY": "ak_env"}):
        tools = AgentGuildTools()

    assert tools.api_key == "ak_env"


@patch("agno.tools.agent_guild.httpx.Client")
def test_check_agent_uses_auth_and_query_contract(mock_client_class):
    response = _success({"verdict": {"recommendation": "hire"}})
    client = mock_client_class.return_value.__enter__.return_value
    client.request.return_value = response
    tools = AgentGuildTools(api_key="ak_test", base_url="https://guild.example/")

    result = tools.check_agent("fact-check", signed=True, ttl_seconds=600)

    assert result["verdict"]["recommendation"] == "hire"
    client.request.assert_called_once_with(
        "GET",
        "https://guild.example/check",
        headers={
            "Accept": "application/json",
            "User-Agent": "agno-agent-guild/1.0",
            "X-API-Key": "ak_test",
        },
        params={"capability": "fact-check", "signed": True, "ttl_seconds": 600},
        json=None,
    )


@patch("agno.tools.agent_guild.httpx.Client")
def test_payment_required_is_actionable_and_does_not_auto_spend(mock_client_class):
    request = httpx.Request("GET", "https://guild.example/check")
    response = MagicMock(spec=httpx.Response)
    response.status_code = 402
    response.json.return_value = {
        "detail": {
            "accepts": [{"network": "eip155:8453", "amount": "10000"}],
            "offer-receipt": {"signature": "large-value-not-needed-by-tool"},
        }
    }
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "payment required", request=request, response=response
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.request.return_value = response
    tools = AgentGuildTools(base_url="https://guild.example")

    result = tools.check_agent("research")

    assert result == {
        "error": "Agent Guild trust checks are metered",
        "status_code": 402,
        "detail": "Pass AGENT_GUILD_API_KEY or explicitly enable request_trial to get free evaluation credits.",
        "payment_options": [{"network": "eip155:8453", "amount": "10000"}],
    }
    assert tools.api_key is None


@patch("agno.tools.agent_guild.httpx.Client")
def test_free_capabilities_request_needs_no_key(mock_client_class):
    response = _success({"supplied": {"research": 3}, "unmet_demand": []})
    client = mock_client_class.return_value.__enter__.return_value
    client.request.return_value = response
    tools = AgentGuildTools(base_url="https://guild.example")

    result = tools.list_capabilities()

    assert result["supplied"] == {"research": 3}
    assert "X-API-Key" not in client.request.call_args.kwargs["headers"]


@patch("agno.tools.agent_guild.httpx.Client")
def test_passport_agent_id_is_path_encoded(mock_client_class):
    response = _success({"type": ["VerifiableCredential"]})
    client = mock_client_class.return_value.__enter__.return_value
    client.request.return_value = response
    tools = AgentGuildTools(base_url="https://guild.example")

    tools.get_passport("agent/a b")

    assert client.request.call_args.args[1] == "https://guild.example/agents/agent%2Fa%20b/passport"


@patch("agno.tools.agent_guild.httpx.Client")
def test_verify_passport_posts_complete_credential(mock_client_class):
    credential = {"type": ["VerifiableCredential"], "proof": {"type": "Ed25519Signature2020"}}
    response = _success({"valid": True})
    client = mock_client_class.return_value.__enter__.return_value
    client.request.return_value = response
    tools = AgentGuildTools(base_url="https://guild.example")

    result = tools.verify_passport(credential)

    assert result == {"valid": True}
    assert client.request.call_args.kwargs["json"] == credential


@patch("agno.tools.agent_guild.httpx.Client")
def test_registration_carries_attribution_and_no_seed_override(mock_client_class):
    response = _success({"id": "agent_123", "did": "did:key:z6Mk", "api_key": "sk_secret"})
    client = mock_client_class.return_value.__enter__.return_value
    client.request.return_value = response
    tools = AgentGuildTools(enable_register_agent=True, base_url="https://guild.example")

    result = tools.register_agent(
        "researcher",
        capabilities=["research"],
        metadata={"endpoint": "https://agent.example/a2a"},
        public_key="abcd",
    )

    assert result["id"] == "agent_123"
    assert client.request.call_args.kwargs["json"] == {
        "name": "researcher",
        "capabilities": ["research"],
        "metadata": {"endpoint": "https://agent.example/a2a"},
        "public_key": "abcd",
        "src": "agno_toolkit",
    }


@patch("agno.tools.agent_guild.httpx.Client")
def test_trial_key_is_reused_for_later_reads(mock_client_class):
    response = _success({"key": "ak_trial", "balance": 100})
    client = mock_client_class.return_value.__enter__.return_value
    client.request.return_value = response
    tools = AgentGuildTools(enable_request_trial=True, base_url="https://guild.example")

    result = tools.request_trial()

    assert result["balance"] == 100
    assert tools.api_key == "ak_trial"


@patch("agno.tools.agent_guild.httpx.Client")
def test_non_json_http_error_preserves_status(mock_client_class):
    request = httpx.Request("GET", "https://guild.example/capabilities")
    response = MagicMock(spec=httpx.Response)
    response.status_code = 503
    response.json.side_effect = ValueError("not json")
    response.text = "temporarily unavailable"
    response.raise_for_status.side_effect = httpx.HTTPStatusError("unavailable", request=request, response=response)
    client = mock_client_class.return_value.__enter__.return_value
    client.request.return_value = response
    tools = AgentGuildTools(base_url="https://guild.example")

    result = tools.list_capabilities()

    assert result == {
        "error": "Agent Guild API request failed",
        "status_code": 503,
        "detail": "temporarily unavailable",
    }


@patch("agno.tools.agent_guild.httpx.Client")
def test_network_error_is_returned_to_agent(mock_client_class):
    request = httpx.Request("GET", "https://guild.example/capabilities")
    client = mock_client_class.return_value.__enter__.return_value
    client.request.side_effect = httpx.ConnectError("offline", request=request)
    tools = AgentGuildTools(base_url="https://guild.example")

    result = tools.list_capabilities()

    assert result["error"] == "Agent Guild API request failed"
    assert "offline" in result["detail"]


@pytest.mark.asyncio
@patch("agno.tools.agent_guild.httpx.AsyncClient")
async def test_async_tool_uses_same_endpoint_contract(mock_client_class):
    response = _success({"valid": True, "live_reputation": {"trust": 91}})
    client = mock_client_class.return_value.__aenter__.return_value
    client.request = AsyncMock(return_value=response)
    tools = AgentGuildTools(api_key="ak_test", base_url="https://guild.example")
    credential = {"id": "urn:uuid:passport"}

    result = await tools.averify_passport(credential)

    assert result["valid"] is True
    client.request.assert_awaited_once_with(
        "POST",
        "https://guild.example/credentials/verify",
        headers={
            "Accept": "application/json",
            "User-Agent": "agno-agent-guild/1.0",
            "X-API-Key": "ak_test",
        },
        params=None,
        json=credential,
    )


@pytest.mark.asyncio
@patch("agno.tools.agent_guild.httpx.AsyncClient")
async def test_async_trial_key_is_reused(mock_client_class):
    response = _success({"key": "ak_async_trial", "balance": 100})
    client = mock_client_class.return_value.__aenter__.return_value
    client.request = AsyncMock(return_value=response)
    tools = AgentGuildTools(enable_request_trial=True, base_url="https://guild.example")

    await tools.arequest_trial()

    assert tools.api_key == "ak_async_trial"
