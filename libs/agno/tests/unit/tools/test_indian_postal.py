from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from agno.tools.indian_postal import IndianPostalTools


@pytest.fixture
def tools():
    return IndianPostalTools()


def response(data, status=200):
    return httpx.Response(
        status, json=data, request=httpx.Request("GET", "https://api.postalpincode.in/pincode/110001")
    )


OFFICE = {"Name": "Connaught Place", "Pincode": "110001", "State": "Delhi"}
SUCCESS = [{"Status": "Success", "Message": "Number of post office(s) found: 1", "PostOffice": [OFFICE]}]


@pytest.mark.parametrize(
    "lookup,query,expected",
    [
        ("get_post_offices_by_pincode", " 110001 ", "Name           : Connaught Place"),
        ("get_post_offices_by_name", "Connaught Place", "PIN Code       : 110001"),
    ],
)
def test_success(tools, lookup, query, expected):
    with patch("agno.tools.indian_postal.httpx.get", return_value=response(SUCCESS)) as get:
        result = getattr(tools, lookup)(query)
    assert expected in result
    assert "State          : Delhi" in result
    assert get.call_args.kwargs["timeout"] == 10.0
    if lookup.endswith("name"):
        assert "%20" in get.call_args.args[0]
    else:
        assert "110001" in get.call_args.args[0]


@pytest.mark.parametrize("pincode", ["123", "1234567", "12A456", "१२३४५६", "", None])
def test_invalid_pincode_does_not_request(tools, pincode):
    with patch("agno.tools.indian_postal.httpx.get") as get:
        assert tools.get_post_offices_by_pincode(pincode).startswith("Error: PIN code")
    get.assert_not_called()


def test_blank_name_does_not_request(tools):
    with patch("agno.tools.indian_postal.httpx.get") as get:
        assert tools.get_post_offices_by_name("  ") == "Error: Branch name cannot be empty."
    get.assert_not_called()


@pytest.mark.parametrize(
    "payload,expected",
    [
        ([{"Status": "Error", "PostOffice": None}], "No post offices found"),
        ([{"Status": "Success", "PostOffice": []}], "No post offices found"),
        ([], "Unexpected response"),
        ({"Status": "Success"}, "Unexpected response"),
        ([{"Status": "Success", "PostOffice": "bad"}], "Unexpected response"),
        ([{"Status": "Success"}], "Unexpected response"),
        ([{"Status": "Success", "PostOffice": [None]}], "Unexpected response"),
        ([{"Status": "Unknown", "PostOffice": [OFFICE]}], "Unexpected response"),
    ],
)
def test_api_payloads(tools, payload, expected):
    with patch("agno.tools.indian_postal.httpx.get", return_value=response(payload)):
        assert expected in tools.get_post_offices_by_pincode("110001")


@pytest.mark.parametrize(
    "failure,expected",
    [
        (response({"error": "failure"}, 503), "Could not reach"),
        (httpx.ConnectError("connection failed"), "Could not reach"),
        (httpx.ReadTimeout("timed out"), "timed out"),
    ],
)
def test_http_failures(tools, failure, expected):
    with patch(
        "agno.tools.indian_postal.httpx.get",
        side_effect=failure if isinstance(failure, Exception) else None,
        return_value=failure if isinstance(failure, httpx.Response) else None,
    ):
        assert expected in tools.get_post_offices_by_name("Bandra")


def test_invalid_json(tools):
    bad = Mock()
    bad.raise_for_status.return_value = None
    bad.json.side_effect = ValueError("bad JSON")
    with patch("agno.tools.indian_postal.httpx.get", return_value=bad):
        assert "Unexpected response" in tools.get_post_offices_by_pincode("110001")


def test_timeout_configuration_and_registration():
    with pytest.raises(ValueError, match="timeout"):
        IndianPostalTools(timeout=0)
    tools = IndianPostalTools(search_by_postoffice=False, timeout=2.5)
    assert list(tools.functions) == ["get_post_offices_by_pincode"]
    assert list(tools.async_functions) == ["get_post_offices_by_pincode"]
    with patch("agno.tools.indian_postal.httpx.get", return_value=response(SUCCESS)) as get:
        tools.get_post_offices_by_pincode("110001")
    assert get.call_args.kwargs["timeout"] == 2.5


@pytest.mark.asyncio
async def test_async_lookup():
    with patch("agno.tools.indian_postal.httpx.AsyncClient") as client_class:
        client = client_class.return_value.__aenter__.return_value
        client.get = AsyncMock(return_value=response(SUCCESS))
        result = await IndianPostalTools().aget_post_offices_by_name("Connaught Place")
    assert "PIN Code       : 110001" in result
    client.get.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,expected",
    [(httpx.ReadTimeout("timed out"), "timed out"), (httpx.ConnectError("offline"), "Could not reach")],
)
async def test_async_failures(failure, expected):
    with patch("agno.tools.indian_postal.httpx.AsyncClient") as client_class:
        client = client_class.return_value.__aenter__.return_value
        client.get = AsyncMock(side_effect=failure)
        assert expected in await IndianPostalTools().aget_post_offices_by_pincode("110001")
