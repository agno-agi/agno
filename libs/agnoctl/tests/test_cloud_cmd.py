"""`agno login`, `agno os register`, and admin tokens from the os.agno.com login."""

import json
import stat
from typing import Any, Dict, List, Optional

import httpx
import pytest
from typer.testing import CliRunner

from agnoctl.cloud import CloudAPI, Credentials, DeviceAuthorization, load_credentials, save_credentials
from agnoctl.main import app

from .conftest import FakeAgentOS, all_output

runner = CliRunner()

CLOUD_HOST = "os-api.agno.com"
OS_URL = "https://my-os.example.com"
SDK_TOKEN = "eyJ.sdk.token"


class FakeCloud:
    """The os.agno.com endpoints the CLI calls, in memory."""

    def __init__(self) -> None:
        self.poll_results: List[Dict[str, Any]] = [{"error": "authorization_pending"}, {"ok": True}]
        self.operating_systems: List[Dict[str, Any]] = []
        self.access_token = "access-1"
        self.refresh_token = "refresh-1"
        self.create_status = 201
        self.sdk_token_status = 200
        self.creates: List[Dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.replace("/api/v1", "", 1)
        if path == "/auth/cli/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://auth.example/device",
                    "verification_uri_complete": "https://auth.example/device?user_code=ABCD-EFGH",
                    "expires_in": 300,
                    "interval": 5,
                },
            )
        if path == "/auth/cli/token":
            result = self.poll_results.pop(0)
            if "error" in result:
                return httpx.Response(400, json={"detail": {"error": result["error"]}})
            return httpx.Response(
                200,
                json={
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "organization_id": "org_1",
                    "email": "dev@example.com",
                },
            )
        if path == "/auth/cli/refresh":
            if json.loads(request.content)["refresh_token"] != self.refresh_token:
                return httpx.Response(400, json={"detail": {"error": "invalid_grant"}})
            self.access_token, self.refresh_token = "access-2", "refresh-2"
            return httpx.Response(200, json={"access_token": "access-2", "refresh_token": "refresh-2"})

        if request.headers.get("Authorization") != "Bearer " + self.access_token:
            return httpx.Response(401, json={"detail": "Could not validate credentials"})
        if path == "/operating-systems/" and request.method == "GET":
            return httpx.Response(200, json=self.operating_systems)
        if path == "/operating-systems/" and request.method == "POST":
            body = json.loads(request.content)
            self.creates.append(body)
            if self.create_status != 201:
                return httpx.Response(
                    self.create_status,
                    json={
                        "detail": {"title": "Payment Required", "detail": "Remote OS access requires a subscription."}
                    },
                )
            registered = {"id": "os-" + str(len(self.creates)), **body}
            self.operating_systems.append(registered)
            return httpx.Response(201, json=registered)
        if path.endswith("/jwt-config"):
            os_id = path.split("/")[2]
            return httpx.Response(
                200,
                json={
                    "jwks_url": "https://os-api.agno.com/api/v1/operating-systems/" + os_id + "/jwks.json",
                    "public_key_pem": "-----BEGIN PUBLIC KEY-----",
                },
            )
        if path == "/auth/sdk-token":
            if self.sdk_token_status != 200:
                return httpx.Response(self.sdk_token_status, json={"detail": {"detail": "Subscription required."}})
            return httpx.Response(200, json={"token": SDK_TOKEN})
        return httpx.Response(404, json={"detail": "Not Found"})


@pytest.fixture
def cloud(monkeypatch, tmp_path) -> FakeCloud:
    """A fake os.agno.com, plus a JWT-mode AgentOS at OS_URL that accepts the sdk-token."""
    import agnoctl.cloud as cloud_module
    import agnoctl.http as http_module

    fake_cloud = FakeCloud()
    fake_os = FakeAgentOS(auth_mode="jwt", security_key=SDK_TOKEN, name="Support OS")

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == CLOUD_HOST:
            return fake_cloud.handler(request)
        return fake_os.handler(request)

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(route))
    monkeypatch.setattr(cloud_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    for var in ("AGNO_ADMIN_TOKEN", "OS_SECURITY_KEY", "AGENTOS_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    fake_cloud.fake_os = fake_os  # type: ignore[attr-defined]
    return fake_cloud


def _logged_in(cloud: FakeCloud) -> None:
    save_credentials(
        Credentials(
            api_url="https://os-api.agno.com",
            access_token=cloud.access_token,
            refresh_token=cloud.refresh_token,
            organization_id="org_1",
            email="dev@example.com",
        )
    )


# -- Login -------------------------------------------------------------------------------


def test_login_stores_credentials_owner_only(cloud, isolated_cloud_login):
    result = runner.invoke(app, ["login", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert "ABCD-EFGH" in all_output(result)
    payload = json.loads(result.stdout)
    assert payload["email"] == "dev@example.com"

    path = isolated_cloud_login / "credentials.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    credentials = load_credentials()
    assert credentials is not None and credentials.refresh_token == "refresh-1"


def test_login_api_url_is_used_by_later_commands(cloud, monkeypatch):
    """`agno login --api-url` points every later command at that control plane, with no env var."""
    import agnoctl.http as http_module

    staging_hosts = []

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "os-api-stg.agno.com":
            staging_hosts.append(request.url.path)
            return cloud.handler(request)
        return httpx.Response(500, json={"detail": "wrong control plane: " + request.url.host})

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(route))
    result = runner.invoke(app, ["login", "--api-url", "https://os-api-stg.agno.com/", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.stdout)["api_url"] == "https://os-api-stg.agno.com"

    result = runner.invoke(app, ["os", "register", "--url", OS_URL, "--name", "S", "--no-env-file", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert "/api/v1/operating-systems/" in staging_hosts


def test_env_var_ignores_login_from_another_control_plane(cloud, monkeypatch):
    _logged_in(cloud)
    monkeypatch.setenv("AGNO_CLOUD_API_URL", "https://os-api-stg.agno.com")
    assert load_credentials() is None


def test_login_denied_fails_without_saving(cloud, isolated_cloud_login):
    cloud.poll_results = [{"error": "access_denied"}]
    result = runner.invoke(app, ["login", "--json"])
    assert result.exit_code == 1
    assert "denied" in json.loads(result.stdout)["error"]
    assert not (isolated_cloud_login / "credentials.json").exists()


def test_slow_down_backs_off(cloud):
    cloud.poll_results = [{"error": "slow_down"}, {"error": "authorization_pending"}, {"ok": True}]
    waits: List[float] = []
    device = DeviceAuthorization("dev-1", "ABCD-EFGH", "https://auth.example/device", None, 300, 5)
    with CloudAPI() as api:
        api.wait_for_device_login(device, sleep=waits.append, clock=lambda: 0.0)
    assert waits == [5.0, 10.0, 10.0]


def test_expired_code_stops_polling(cloud):
    cloud.poll_results = [{"error": "expired_token"}]
    device = DeviceAuthorization("dev-1", "ABCD-EFGH", "https://auth.example/device", None, 300, 5)
    with CloudAPI() as api, pytest.raises(Exception, match="expired"):
        api.wait_for_device_login(device, sleep=lambda s: None, clock=lambda: 0.0)


def test_logout_removes_login(cloud, isolated_cloud_login):
    _logged_in(cloud)
    result = runner.invoke(app, ["logout", "--json"])
    assert json.loads(result.stdout)["logged_out"] is True
    assert load_credentials() is None


# -- Register ----------------------------------------------------------------------------


def test_register_creates_os_and_writes_jwks_url(cloud, tmp_path):
    _logged_in(cloud)
    env = tmp_path / ".env.production"
    env.write_text("OPENAI_API_KEY=sk-test\nJWT_JWKS_URL=https://old.example/jwks.json\n")

    result = runner.invoke(app, ["os", "register", "--url", OS_URL, "--json"])
    assert result.exit_code == 0, all_output(result)
    payload = json.loads(result.stdout)
    assert payload["created"] is True
    assert cloud.creates == [{"name": "Support OS", "endpoint_url": OS_URL, "enabled_jwt": True}]
    assert env.read_text() == (
        "OPENAI_API_KEY=sk-test\nJWT_JWKS_URL=https://os-api.agno.com/api/v1/operating-systems/os-1/jwks.json\n"
    )


def test_register_is_idempotent(cloud, tmp_path):
    _logged_in(cloud)
    runner.invoke(app, ["os", "register", "--url", OS_URL, "--json"])
    result = runner.invoke(app, ["os", "register", "--url", OS_URL + "/", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.stdout)["created"] is False
    assert len(cloud.creates) == 1


def test_register_reads_url_from_env_file(cloud, tmp_path):
    _logged_in(cloud)
    (tmp_path / ".env.production").write_text("AGENTOS_URL=" + OS_URL + "\n")
    result = runner.invoke(app, ["os", "register", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert "JWT_JWKS_URL=" in (tmp_path / ".env.production").read_text()


def test_register_shows_billing_without_subscribing(cloud):
    _logged_in(cloud)
    cloud.create_status = 402
    result = runner.invoke(app, ["os", "register", "--url", OS_URL, "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert "subscription" in payload["error"]
    assert "payment method" in payload["hint"]


def test_register_requires_login(cloud):
    result = runner.invoke(app, ["os", "register", "--url", OS_URL, "--json"])
    assert result.exit_code == 1
    assert "agno login" in json.loads(result.stdout)["hint"]


def test_register_rejects_plaintext_remote_url(cloud):
    _logged_in(cloud)
    result = runner.invoke(app, ["os", "register", "--url", "http://my-os.example.com", "--json"])
    assert result.exit_code == 1
    assert cloud.creates == []


def test_register_accepts_local_os(cloud):
    _logged_in(cloud)
    result = runner.invoke(app, ["os", "register", "--url", "http://localhost:7777", "--name", "Local", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert cloud.creates[0]["endpoint_url"] == "http://localhost:7777"


def test_expired_access_token_is_refreshed_and_saved(cloud):
    _logged_in(cloud)
    cloud.access_token = "access-rotated-server-side"  # the stored access token no longer works
    result = runner.invoke(app, ["os", "register", "--url", OS_URL, "--no-env-file", "--json"])
    assert result.exit_code == 0, all_output(result)
    stored: Optional[Credentials] = load_credentials()
    assert stored is not None and stored.access_token == "access-2" and stored.refresh_token == "refresh-2"


# -- Admin token from the login ------------------------------------------------------------


def test_tokens_create_uses_cloud_login_on_jwt_os(cloud):
    _logged_in(cloud)
    runner.invoke(app, ["os", "register", "--url", OS_URL, "--no-env-file", "--json"])
    result = runner.invoke(app, ["tokens", "create", "ci-runner", "--url", OS_URL, "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.stdout)["token"].startswith("agno_pat_")
    assert "ci-runner" in cloud.fake_os.accounts  # type: ignore[attr-defined]


def test_unregistered_os_falls_back_to_credential_error(cloud):
    _logged_in(cloud)
    result = runner.invoke(app, ["tokens", "create", "ci-runner", "--url", OS_URL, "--json"])
    assert result.exit_code == 1
    assert "agno login" in json.loads(result.stdout)["hint"]


def test_lapsed_subscription_is_reported(cloud):
    _logged_in(cloud)
    runner.invoke(app, ["os", "register", "--url", OS_URL, "--no-env-file", "--json"])
    cloud.sdk_token_status = 402
    result = runner.invoke(app, ["tokens", "create", "ci-runner", "--url", OS_URL, "--json"])
    assert result.exit_code == 1
    assert "payment method" in json.loads(result.stdout)["hint"]


def test_env_credential_wins_over_login(cloud, monkeypatch):
    _logged_in(cloud)
    runner.invoke(app, ["os", "register", "--url", OS_URL, "--no-env-file", "--json"])
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", "explicit-but-wrong")
    result = runner.invoke(app, ["tokens", "create", "ci-runner", "--url", OS_URL, "--json"])
    assert result.exit_code == 1
    assert "rejected the admin credential" in json.loads(result.stdout)["error"]
