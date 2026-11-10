"""Unit tests for OutageDeckTools."""

from unittest.mock import Mock, patch

import httpx
import pytest

from agno.tools.outagedeck import API_BASE_URL, USER_AGENT, OutageDeckTools


@pytest.fixture
def tools():
    return OutageDeckTools(timeout=7)


def _response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _provider_payload():
    return {
        "data": {
            "slug": "github",
            "name": "GitHub",
            "currentStatus": {
                "code": "degraded",
                "label": "Degraded Performance",
                "headline": "Some systems are degraded",
                "summary": "GitHub reports degraded performance.",
                "capturedAt": "2026-08-05T12:00:00Z",
            },
            "counts": {"services": 3, "activeIncidents": 1, "incidents": 10},
            "services": [
                {
                    "slug": "github-actions",
                    "name": "GitHub Actions",
                    "category": "ci-cd",
                    "status": "degraded",
                    "summary": "Workflow execution.",
                }
            ],
            "activeIncidents": [_incident_payload()],
        }
    }


def _incident_payload():
    return {
        "slug": "github-actions-delays-2026-08-05",
        "title": "Actions delays",
        "summary": "Some workflow runs are delayed.",
        "status": "monitoring",
        "severity": "major",
        "startedAt": "2026-08-05T10:00:00Z",
        "updatedAt": "2026-08-05T11:00:00Z",
        "resolvedAt": None,
        "provider": {"slug": "github", "name": "GitHub"},
        "affectedServices": [{"slug": "github-actions", "name": "GitHub Actions"}],
    }


def _service_payload():
    return {
        "data": {
            "slug": "github-actions",
            "name": "GitHub Actions",
            "category": "ci-cd",
            "status": "degraded",
            "summary": "Workflow execution.",
            "provider": {"slug": "github", "name": "GitHub"},
            "counts": {"incidents": 12, "activeIncidents": 1},
            "incidents": [_incident_payload()] * 12,
        }
    }


def test_registers_all_tools_and_async_variants(tools):
    assert set(tools.functions) == {"get_provider_status", "list_incidents", "get_service_status"}
    assert set(tools.async_functions) == {"get_provider_status", "list_incidents", "get_service_status"}


def test_selective_registration():
    tools = OutageDeckTools(
        enable_provider_status=False,
        enable_incidents=True,
        enable_service_status=False,
    )
    assert set(tools.functions) == {"list_incidents"}
    assert set(tools.async_functions) == {"list_incidents"}


@pytest.mark.parametrize(
    "method,value",
    [
        ("get_provider_status", "../admin"),
        ("get_provider_status", "github/status"),
        ("get_provider_status", "github?limit=100"),
        ("get_service_status", "-github-actions"),
        ("get_service_status", "github--actions"),
        ("get_service_status", ""),
    ],
)
def test_rejects_invalid_slugs_without_network(tools, method, value):
    with patch("agno.tools.outagedeck.httpx.Client") as client:
        result = getattr(tools, method)(value)
    assert "error" in result
    client.assert_not_called()


def test_get_provider_status_sends_exact_request_and_parses_response(tools):
    with patch("agno.tools.outagedeck.httpx.Client") as client:
        instance = client.return_value.__enter__.return_value
        instance.get.return_value = _response(_provider_payload())
        result = tools.get_provider_status(" GitHub ")

    instance.get.assert_called_once_with(
        f"{API_BASE_URL}/providers/github",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    assert result["status"]["code"] == "degraded"
    assert result["services"][0]["slug"] == "github-actions"
    assert result["active_incidents"][0]["severity"] == "major"
    assert "utm_campaign=agno_toolkit" in result["outagedeck_url"]


def test_list_incidents_sends_filters_and_parses_pagination(tools):
    payload = {
        "data": {
            "count": 1,
            "page": 2,
            "totalPages": 4,
            "totalIncidents": 7,
            "incidents": [_incident_payload()],
        }
    }
    with patch("agno.tools.outagedeck.httpx.Client") as client:
        instance = client.return_value.__enter__.return_value
        instance.get.return_value = _response(payload)
        result = tools.list_incidents(" GitHub ", state="ACTIVE", severity="Major", page=2, limit=5)

    instance.get.assert_called_once_with(
        f"{API_BASE_URL}/incidents",
        params={"page": 2, "limit": 5, "provider": "github", "state": "active", "severity": "major"},
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    assert result["total_pages"] == 4
    assert result["incidents"][0]["affected_services"][0]["slug"] == "github-actions"
    assert "utm_source=agno" in result["incidents"][0]["outagedeck_url"]


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"page": 0}, "Page"),
        ({"page": True}, "Page"),
        ({"limit": 101}, "Limit"),
        ({"limit": False}, "Limit"),
        ({"state": "investigating"}, "State"),
        ({"severity": "catastrophic"}, "Severity"),
        ({"provider": "github/api"}, "slug"),
    ],
)
def test_list_incidents_validates_filters_without_network(tools, kwargs, error):
    with patch("agno.tools.outagedeck.httpx.Client") as client:
        result = tools.list_incidents(**kwargs)
    assert error in result["error"]
    client.assert_not_called()


def test_get_service_status_caps_incidents_for_agent_context(tools):
    with patch("agno.tools.outagedeck.httpx.Client") as client:
        instance = client.return_value.__enter__.return_value
        instance.get.return_value = _response(_service_payload())
        result = tools.get_service_status("github-actions")

    assert result["service"]["status"] == "degraded"
    assert result["provider"] == {"slug": "github", "name": "GitHub"}
    assert len(result["recent_incidents"]) == 10
    assert "utm_medium=integration" in result["outagedeck_url"]


@pytest.mark.parametrize(
    "status,expected",
    [(404, "could not find"), (429, "rate limit"), (500, "HTTP 500")],
)
def test_http_errors_are_actionable(tools, status, expected):
    request = httpx.Request("GET", f"{API_BASE_URL}/providers/missing")
    response = httpx.Response(status, request=request)
    error = httpx.HTTPStatusError("failed", request=request, response=response)
    with patch("agno.tools.outagedeck.httpx.Client") as client:
        instance = client.return_value.__enter__.return_value
        instance.get.return_value.raise_for_status.side_effect = error
        result = tools.get_provider_status("missing")
    assert expected.lower() in result["error"].lower()


def test_network_error_is_actionable(tools):
    request = httpx.Request("GET", f"{API_BASE_URL}/incidents")
    with patch("agno.tools.outagedeck.httpx.Client") as client:
        instance = client.return_value.__enter__.return_value
        instance.get.side_effect = httpx.ConnectError("connection refused", request=request)
        result = tools.list_incidents()
    assert "Could not reach OutageDeck" in result["error"]


def test_invalid_json_is_actionable(tools):
    with patch("agno.tools.outagedeck.httpx.Client") as client:
        instance = client.return_value.__enter__.return_value
        response = _response({})
        response.json.side_effect = ValueError("invalid JSON")
        instance.get.return_value = response
        result = tools.get_provider_status("github")
    assert "invalid JSON response" in result["error"]


@pytest.mark.parametrize("method", ["get_provider_status", "list_incidents", "get_service_status"])
def test_unexpected_response_shape_is_actionable(tools, method):
    with patch("agno.tools.outagedeck.httpx.Client") as client:
        instance = client.return_value.__enter__.return_value
        instance.get.return_value = _response({"data": []})
        result = getattr(tools, method)("github" if method != "list_incidents" else None)
    assert "unexpected" in result["error"]


@pytest.mark.asyncio
async def test_async_provider_status_matches_sync_behavior(tools):
    async def get(*args, **kwargs):
        return _response(_provider_payload())

    with patch("agno.tools.outagedeck.httpx.AsyncClient") as client:
        instance = client.return_value.__aenter__.return_value
        instance.get.side_effect = get
        result = await tools.aget_provider_status("github")

    instance.get.assert_called_once_with(
        f"{API_BASE_URL}/providers/github",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    assert result["provider"]["name"] == "GitHub"


@pytest.mark.asyncio
async def test_async_incidents_matches_sync_behavior(tools):
    payload = {
        "data": {"count": 1, "page": 1, "totalPages": 1, "totalIncidents": 1, "incidents": [_incident_payload()]}
    }

    async def get(*args, **kwargs):
        return _response(payload)

    with patch("agno.tools.outagedeck.httpx.AsyncClient") as client:
        instance = client.return_value.__aenter__.return_value
        instance.get.side_effect = get
        result = await tools.alist_incidents(provider="github", state="active", limit=1)

    assert result["count"] == 1
    assert result["incidents"][0]["title"] == "Actions delays"


@pytest.mark.asyncio
async def test_async_service_status_matches_sync_behavior(tools):
    async def get(*args, **kwargs):
        return _response(_service_payload())

    with patch("agno.tools.outagedeck.httpx.AsyncClient") as client:
        instance = client.return_value.__aenter__.return_value
        instance.get.side_effect = get
        result = await tools.aget_service_status("github-actions")

    assert result["service"]["name"] == "GitHub Actions"
