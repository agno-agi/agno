import json
from unittest.mock import MagicMock, patch

import httpx

from agno.tools.darkmoon import DarkmoonTools

BASE = "http://darkmoon.test:8000"
FINDING = {"title": "Reflected XSS in /search", "severity": "high", "cvss_score": 7.4, "status": "confirmed"}


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def _response(status_code=200, body=None):
    return _Response(status_code, body)


class FakeDarkmoon:
    """Routes httpx.Client.request calls to canned Dashboard API responses."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, headers=None, json=None):
        path = url[len(BASE) :]
        self.calls.append((method, path, headers, json))
        handler = self.routes.get((method, path.split("?")[0]))
        if handler is None:
            return _response(404, {"detail": "Not found"})
        return handler if isinstance(handler, _Response) else handler()


def _patched(fake):
    client = MagicMock()
    client.request.side_effect = fake.request
    client_class = MagicMock()
    client_class.return_value.__enter__.return_value = client
    return patch("agno.tools.darkmoon.httpx.Client", client_class)


def _tools(**kwargs):
    return DarkmoonTools(base_url=BASE + "/", username="admin", password="secret", **kwargs)


LOGIN = _response(200, {"token": "jwt-123"})


def test_initialization_registers_tools():
    tools = _tools()
    assert tools.name == "darkmoon_tools"
    assert set(tools.functions) == {"run_pentest", "get_findings", "list_campaigns"}


def test_disabled_tool_is_not_registered():
    tools = _tools(enable_run_pentest=False)
    assert "run_pentest" not in tools.functions
    assert "get_findings" in tools.functions


def test_connection_read_from_environment():
    env = {"DARKMOON_BASE_URL": BASE, "DARKMOON_USERNAME": "u", "DARKMOON_PASSWORD": "p"}
    with patch.dict("os.environ", env):
        tools = DarkmoonTools()
    assert (tools.base_url, tools.username, tools.password) == (BASE, "u", "p")


def test_missing_connection_returns_error():
    with patch.dict("os.environ", {}, clear=True):
        tools = DarkmoonTools()
    assert "Missing Darkmoon connection settings" in json.loads(tools.list_campaigns())["error"]


def test_list_campaigns_logs_in_once_and_sends_bearer():
    fake = FakeDarkmoon(
        {
            ("POST", "/api/v1/auth/login"): LOGIN,
            ("GET", "/api/v1/campaigns"): _response(200, {"data": [{"id": "camp_1"}]}),
        }
    )
    tools = _tools()
    with _patched(fake):
        first = json.loads(tools.list_campaigns())
        tools.list_campaigns()

    assert first == {"total": 1, "campaigns": [{"id": "camp_1"}]}
    assert [c[1] for c in fake.calls].count("/api/v1/auth/login") == 1
    assert fake.calls[0][3] == {"username": "admin", "password": "secret"}
    assert "Authorization" not in fake.calls[0][2]
    assert fake.calls[1][2]["Authorization"] == "Bearer jwt-123"


def test_get_findings_returns_findings_and_stats():
    fake = FakeDarkmoon(
        {
            ("POST", "/api/v1/auth/login"): LOGIN,
            ("GET", "/api/v1/vulnerabilities"): _response(200, {"data": [FINDING], "total": 1, "stats": {"high": 1}}),
        }
    )
    with _patched(fake):
        result = json.loads(_tools().get_findings("camp 1"))

    assert result == {"campaign_id": "camp 1", "total": 1, "stats": {"high": 1}, "findings": [FINDING]}
    assert fake.calls[-1][1] == "/api/v1/vulnerabilities?campaign_id=camp%201"


def test_get_findings_requires_campaign_id():
    assert "campaign id is required" in json.loads(_tools().get_findings("  "))["error"]


def test_api_error_detail_is_returned_without_secrets():
    fake = FakeDarkmoon({("POST", "/api/v1/auth/login"): _response(401, {"detail": "Bad credentials"})})
    with _patched(fake):
        error = json.loads(_tools().list_campaigns())["error"]
    assert "401" in error and "Bad credentials" in error
    assert "secret" not in error


def test_network_failure_is_returned_as_error():
    client_class = MagicMock()
    client_class.return_value.__enter__.return_value.request.side_effect = httpx.ConnectError("refused")
    with patch("agno.tools.darkmoon.httpx.Client", client_class):
        error = json.loads(_tools().list_campaigns())["error"]
    assert "Request to Darkmoon failed" in error


def _run_routes(log_batches, campaigns_before, campaigns_after):
    campaign_lists = iter([campaigns_before, campaigns_after])
    logs = iter(log_batches)
    return {
        ("POST", "/api/v1/auth/login"): LOGIN,
        ("GET", "/api/v1/campaigns"): lambda: _response(200, {"data": next(campaign_lists)}),
        ("POST", "/api/v1/run/campaign"): _response(200, {"run_id": "run_9", "pid": 42}),
        ("GET", "/api/v1/run/logs/run_9"): lambda: _response(200, {"data": next(logs)}),
        ("GET", "/api/v1/vulnerabilities"): _response(200, {"data": [FINDING], "total": 1, "stats": {"high": 1}}),
    }


def test_run_pentest_waits_and_returns_findings_of_the_new_campaign():
    fake = FakeDarkmoon(
        _run_routes(
            [[{"type": "run_started"}], [{"type": "run_started"}, {"type": "run_completed"}]],
            [{"id": "camp_old", "date": "2026-01-01"}],
            [{"id": "camp_old", "date": "2026-01-01"}, {"id": "camp_new_app.test", "date": "2026-10-02"}],
        )
    )
    with _patched(fake), patch("agno.tools.darkmoon.time.sleep") as sleep:
        result = json.loads(_tools().run_pentest("app.test", focus="auth, injection", severity="high"))

    start = next(c for c in fake.calls if c[1] == "/api/v1/run/campaign")
    assert start[3] == {"target": "app.test", "focus": ["auth", "injection"], "severity": "high"}
    assert sleep.call_count == 1
    assert result["run_id"] == "run_9"
    assert result["campaign_id"] == "camp_new_app.test"
    assert result["timed_out"] is False
    assert result["findings"] == [FINDING]


def test_run_pentest_without_waiting_returns_run_id():
    fake = FakeDarkmoon(_run_routes([], [], []))
    with _patched(fake):
        result = json.loads(_tools().run_pentest("app.test", wait_for_completion=False))
    assert result == {"status": "started", "run_id": "run_9", "target": "app.test"}
    assert not any("/run/logs/" in call[1] for call in fake.calls)


def test_run_pentest_reports_timeout_and_never_a_preexisting_campaign():
    campaigns = [{"id": "camp_old", "date": "2026-01-01"}]
    fake = FakeDarkmoon(_run_routes([[{"type": "run_started"}]] * 5, campaigns, campaigns))
    clock = iter([0.0, 0.0, 10.0, 10.0])
    with (
        _patched(fake),
        patch("agno.tools.darkmoon.time.sleep"),
        patch("agno.tools.darkmoon.time.monotonic", lambda: next(clock)),
    ):
        result = json.loads(_tools().run_pentest("app.test", timeout_seconds=5))
    assert result["timed_out"] is True
    assert result["campaign_id"] is None
    assert result["findings"] == []


def test_run_pentest_rejects_blank_target():
    assert "target is required" in json.loads(_tools().run_pentest("   "))["error"]
