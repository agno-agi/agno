import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agno.tools.tensorust import TensorustTools


def _rpc(payload, is_error=False):
    """A JSON-RPC tools/call result as the Tensorust endpoint returns it."""
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=1)
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}},
    )


ORG = {"found": True, "oid": "org:INVITATION HOMES", "name": "Invitation Homes Inc.", "access": "preview"}

SANCTIONS = {
    "mode": "search",
    "total": 1,
    "items": [{"oid": "sanction:30947", "name": "HUAWEI TECHNOLOGIES CO., LTD.", "type": "Sanction"}],
}

SCREEN = {
    "stored": False,
    "as_of": "2026-11-13",
    "lists_pulled": "2026-11-13T11:32:16Z",
    "matched_lines": 1,
    "by_vendor": {"huawei": {"lists": ["1260H", "FCC_COVERED", "SEC889"]}},
    "by_rule": {"889-GRANTS": {"check_funding_source": {"lines": 1, "usd": 0}}},
    "ledger_join": {"note": "not relevant for one name"},
    "items": [{"row": 1, "flags": [{"rule": "889-GRANTS", "severity": "review", "citation": "2 CFR 200.216"}]}],
}


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("TENSORUST_API_KEY", raising=False)
    monkeypatch.delenv("TENSORUST_API_URL", raising=False)


def _sent(mock_post, index=-1):
    call = mock_post.call_args_list[index]
    return call.args[0], call.kwargs["json"], call.kwargs["headers"]


def test_keyless_by_default_sends_no_key_and_no_full_flag():
    tools = TensorustTools()
    assert tools.api_key is None

    with patch("agno.tools.tensorust.httpx.post", return_value=_rpc(ORG)) as mock_post:
        output = tools.lookup_organization("Invitation Homes")

    url, body, headers = _sent(mock_post)
    assert url == "https://shop.tensorust.com/api/mcp"
    assert body == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "lookup_organization", "arguments": {"name": "Invitation Homes"}},
    }
    assert "Authorization" not in headers
    assert json.loads(output)["oid"] == "org:INVITATION HOMES"


def test_api_key_sends_bearer_and_requests_full_record():
    tools = TensorustTools(api_key="tdk_test")

    with patch("agno.tools.tensorust.httpx.post", return_value=_rpc(ORG)) as mock_post:
        tools.get_lender_marks("Pluralsight")

    _, body, headers = _sent(mock_post)
    assert headers["Authorization"] == "Bearer tdk_test"
    assert body["params"] == {"name": "lender_marks", "arguments": {"name": "Pluralsight", "full": True}}


def test_api_key_and_url_from_env(monkeypatch):
    monkeypatch.setenv("TENSORUST_API_KEY", "tdk_env")
    monkeypatch.setenv("TENSORUST_API_URL", "https://staging.example.com/api/mcp/")
    tools = TensorustTools()
    assert tools.api_key == "tdk_env"
    assert tools.base_url == "https://staging.example.com/api/mcp"


def test_plain_http_is_refused_except_on_loopback():
    with patch("agno.tools.tensorust.httpx.post") as mock_post:
        output = TensorustTools(base_url="http://example.com/api/mcp").lookup_organization("x")
    assert output.startswith("Error calling Tensorust")
    mock_post.assert_not_called()

    with patch("agno.tools.tensorust.httpx.post", return_value=_rpc(ORG)) as mock_post:
        TensorustTools(base_url="http://localhost:3000/api/mcp").lookup_organization("x")
    assert _sent(mock_post)[0] == "http://localhost:3000/api/mcp"


def test_default_and_all_registration():
    default = sorted(f.name for f in TensorustTools().functions.values())
    assert default == [
        "get_contractor_credit",
        "get_lender_marks",
        "lookup_organization",
        "screen_counterparty",
        "who_owns_home",
    ]
    every = sorted(f.name for f in TensorustTools(all=True).functions.values())
    assert every == sorted(default + ["get_idr_offer"])
    assert sorted(f.name for f in TensorustTools(all=True).async_functions.values()) == every
    assert TensorustTools().name == "tensorust_tools"


def test_flags_select_tools():
    tools = TensorustTools(
        enable_lookup_organization=False,
        enable_who_owns_home=False,
        enable_get_lender_marks=False,
        enable_get_contractor_credit=False,
    )
    assert [f.name for f in tools.functions.values()] == ["screen_counterparty"]


def test_who_owns_home_maps_zip_argument():
    answer = {"address": "2746 Lofty Elm St", "zip": "77494", "entity_owned": False}
    with patch("agno.tools.tensorust.httpx.post", return_value=_rpc(answer)) as mock_post:
        TensorustTools().who_owns_home(" 2746 Lofty Elm St ", "77494")
    _, body, _ = _sent(mock_post)
    assert body["params"] == {"name": "who_owns_home", "arguments": {"address": "2746 Lofty Elm St", "zip": "77494"}}


def test_contractor_credit_tool_name():
    with patch("agno.tools.tensorust.httpx.post", return_value=_rpc({"found": True})) as mock_post:
        TensorustTools().get_contractor_credit("Peraton")
    assert _sent(mock_post)[1]["params"]["name"] == "contractor_credit"


def test_idr_offer_omits_empty_optionals_and_uppercases_state():
    with patch("agno.tools.tensorust.httpx.post", return_value=_rpc({"ok": True})) as mock_post:
        tools = TensorustTools(all=True)
        tools.get_idr_offer("99284", payer="uhc.com", state="tx", qpa=180.0)
        tools.get_idr_offer("99284")
    assert _sent(mock_post, 0)[1]["params"]["arguments"] == {
        "code": "99284",
        "payer": "uhc.com",
        "state": "TX",
        "qpa": 180.0,
    }
    assert _sent(mock_post, 1)[1]["params"]["arguments"] == {"code": "99284"}


def test_screen_counterparty_merges_sanctions_and_vendor_lists():
    with patch("agno.tools.tensorust.httpx.post", side_effect=[_rpc(SANCTIONS), _rpc(SCREEN)]) as mock_post:
        output = TensorustTools().screen_counterparty("Huawei")

    assert _sent(mock_post, 0)[1]["params"] == {
        "name": "query_ontology",
        "arguments": {"name": "Huawei", "type": "Sanction", "limit": 10},
    }
    assert _sent(mock_post, 1)[1]["params"] == {
        "name": "exposure_screen_purchases",
        "arguments": {"lines": [{"vendor": "Huawei"}]},
    }
    result = json.loads(output)
    assert result["sanctions"]["total"] == 1
    assert result["sanctions"]["matches"][0]["oid"] == "sanction:30947"
    vendor = result["restricted_vendor_lists"]
    assert vendor["by_vendor"]["huawei"]["lists"] == ["1260H", "FCC_COVERED", "SEC889"]
    assert vendor["flags"] == [{"rule": "889-GRANTS", "severity": "review", "citation": "2 CFR 200.216"}]
    assert "ledger_join" not in vendor


def test_screen_counterparty_keeps_partial_answer_on_error():
    failed = httpx.Response(500, text="boom")
    with patch("agno.tools.tensorust.httpx.post", side_effect=[_rpc(SANCTIONS), failed]):
        result = json.loads(TensorustTools().screen_counterparty("Huawei"))
    assert result["sanctions"]["total"] == 1
    assert result["restricted_vendor_lists"]["error"] == "Error: Tensorust API error (500)"


def test_empty_arguments_are_rejected_without_a_request():
    tools = TensorustTools(all=True)
    with patch("agno.tools.tensorust.httpx.post") as mock_post:
        assert tools.lookup_organization("  ").startswith("Error")
        assert tools.who_owns_home("1 Main St", "").startswith("Error")
        assert tools.get_lender_marks("").startswith("Error")
        assert tools.get_contractor_credit("").startswith("Error")
        assert tools.screen_counterparty("").startswith("Error")
        assert tools.get_idr_offer("").startswith("Error")
    mock_post.assert_not_called()


def test_tool_error_result_is_reported():
    with patch("agno.tools.tensorust.httpx.post", return_value=_rpc("name is required", is_error=True)):
        assert TensorustTools().lookup_organization("x") == "Error: name is required"


def test_jsonrpc_error_is_reported():
    response = httpx.Response(
        200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Unknown tool"}}
    )
    with patch("agno.tools.tensorust.httpx.post", return_value=response):
        assert TensorustTools().lookup_organization("x") == "Error: Unknown tool"


@pytest.mark.parametrize(
    "response, expected",
    [
        (httpx.Response(401, json={}), "Error: Tensorust authentication failed (401): check TENSORUST_API_KEY"),
        (httpx.Response(429, json={}), "Error: Tensorust rate limit exceeded (429)"),
        (httpx.Response(200, text="<html>"), "Error: the Tensorust API returned a non-JSON response."),
        (httpx.Response(200, json=[1, 2]), "Error: unexpected response from the Tensorust API."),
        (httpx.Response(200, json={"result": {}}), "Error: unexpected response from the Tensorust API."),
    ],
)
def test_bad_responses_become_messages(response, expected):
    with patch("agno.tools.tensorust.httpx.post", return_value=response):
        assert TensorustTools().lookup_organization("x") == expected


def test_network_error_is_reported():
    with patch("agno.tools.tensorust.httpx.post", side_effect=httpx.ConnectError("refused")):
        assert TensorustTools().lookup_organization("x") == "Error calling Tensorust: refused"


@pytest.mark.asyncio
async def test_async_variants_use_async_client():
    client = AsyncMock()
    client.post.side_effect = [_rpc(ORG), _rpc(SANCTIONS), _rpc(SCREEN)]
    client.__aenter__.return_value = client
    tools = TensorustTools(api_key="tdk_test")

    with patch("agno.tools.tensorust.httpx.AsyncClient", return_value=client):
        org = await tools.alookup_organization("Invitation Homes")
        screen = await tools.ascreen_counterparty("Huawei")

    assert json.loads(org)["oid"] == "org:INVITATION HOMES"
    first = client.post.call_args_list[0]
    assert first.kwargs["json"]["params"]["arguments"] == {"name": "Invitation Homes", "full": True}
    assert first.kwargs["headers"]["Authorization"] == "Bearer tdk_test"
    assert json.loads(screen)["sanctions"]["total"] == 1


@pytest.mark.asyncio
async def test_async_variants_validate_arguments():
    tools = TensorustTools(all=True)
    with patch("agno.tools.tensorust.httpx.AsyncClient") as mock_client:
        assert (await tools.awho_owns_home("", "77494")).startswith("Error")
        assert (await tools.aget_lender_marks(" ")).startswith("Error")
        assert (await tools.aget_contractor_credit("")).startswith("Error")
        assert (await tools.ascreen_counterparty("")).startswith("Error")
        assert (await tools.aget_idr_offer("")).startswith("Error")
    mock_client.assert_not_called()
