"""Client for the AgentOS control plane (os.agno.com) and the CLI's stored login.

`agno login` signs in with the OAuth 2.0 device flow (RFC 8628): the control plane
returns a user code and a verification URL, the user approves in a browser, and the
CLI polls until it receives tokens. The tokens are stored in the user's config
directory, readable only by the user, and refreshed when they expire.

With a login, the CLI can register a deployed AgentOS on the control plane and fetch a
short-lived admin token for it, so a coding agent never needs a human to paste keys.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

import httpx

from agnoctl.errors import APIError, CLIError
from agnoctl.http import DEFAULT_TIMEOUT, build_client

CLOUD_API_ENV = "AGNO_CLOUD_API_URL"
DEFAULT_CLOUD_API_URL = "https://os-api.agno.com"
CLOUD_APP_URL = "https://os.agno.com"
CONFIG_DIR_ENV = "AGNO_CONFIG_DIR"
CREDENTIALS_FILE = "credentials.json"

LOGIN_HINT = "Run `agno login` to sign in to " + CLOUD_APP_URL + "."
BILLING_HINT = (
    "Remote AgentOS instances need an active subscription. Add a payment method at "
    + CLOUD_APP_URL
    + " and run the command again."
)


def cloud_api_url(credentials: Optional["Credentials"] = None) -> str:
    """The control-plane URL: AGNO_CLOUD_API_URL, then the URL the stored login came from,
    then production. `agno login --api-url` saves the URL, so later commands follow it."""
    url = os.environ.get(CLOUD_API_ENV) or (credentials.api_url if credentials else None) or DEFAULT_CLOUD_API_URL
    return url.rstrip("/")


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / "agno"


def normalize_url(url: str) -> str:
    """Compare AgentOS URLs by scheme, host and path, ignoring case and a trailing slash."""
    parts = urlsplit(url.strip())
    return parts.scheme.lower() + "://" + parts.netloc.lower() + parts.path.rstrip("/")


@dataclass
class Credentials:
    api_url: str
    access_token: str
    refresh_token: str
    organization_id: Optional[str] = None
    email: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_url": self.api_url,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "organization_id": self.organization_id,
            "email": self.email,
        }


def credentials_path() -> Path:
    return config_dir() / CREDENTIALS_FILE


def load_credentials() -> Optional[Credentials]:
    """The stored login, or None. A login from a different control plane than an
    exported AGNO_CLOUD_API_URL is ignored."""
    path = credentials_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("access_token") or not data.get("refresh_token"):
        return None
    env_url = os.environ.get(CLOUD_API_ENV)
    if not data.get("api_url") or (env_url and data["api_url"].rstrip("/") != env_url.rstrip("/")):
        return None
    return Credentials(
        api_url=data["api_url"],
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        organization_id=data.get("organization_id"),
        email=data.get("email"),
    )


def save_credentials(credentials: Credentials) -> Path:
    """Write the login with owner-only permissions. The file holds a refresh token."""
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    # Create the file 0600 before any secret is written, then replace it atomically.
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(credentials.to_dict(), f, indent=2)
    os.replace(tmp, path)
    return path


def delete_credentials() -> bool:
    try:
        credentials_path().unlink()
        return True
    except FileNotFoundError:
        return False


def _problem_detail(response: httpx.Response) -> str:
    """The message from a control-plane error: a string detail, a problem-detail object or {error}."""
    try:
        detail = response.json().get("detail")
    except Exception:
        return "HTTP " + str(response.status_code)
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, dict):
        for key in ("detail", "error"):
            value = detail.get(key)
            if isinstance(value, str) and value:
                return value
    return "HTTP " + str(response.status_code)


def _oauth_error(response: httpx.Response) -> Optional[str]:
    try:
        detail = response.json().get("detail")
    except Exception:
        return None
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        return detail["error"]
    return None


@dataclass
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str]
    expires_in: int
    interval: int


@dataclass
class RegisteredOS:
    id: str
    name: str
    endpoint_url: str
    enabled_jwt: bool

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegisteredOS":
        return cls(
            id=str(data["id"]),
            name=data.get("name") or "",
            endpoint_url=data.get("endpoint_url") or "",
            enabled_jwt=bool(data.get("enabled_jwt")),
        )


class CloudAPI:
    """Sync client for the control-plane endpoints the CLI uses.

    Requests made with a login send it as a bearer token. On a 401 the client refreshes
    the login once, stores the rotated tokens, and retries.
    """

    def __init__(
        self,
        credentials: Optional[Credentials] = None,
        api_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_url = (api_url or cloud_api_url(credentials)).rstrip("/")
        self.credentials = credentials
        self._client = build_client(base_url=self.api_url + "/api/v1", timeout=timeout)

    @classmethod
    def logged_in(cls) -> "CloudAPI":
        credentials = load_credentials()
        if credentials is None:
            raise CLIError("You are not signed in to " + CLOUD_APP_URL + ".", hint=LOGIN_HINT)
        return cls(credentials)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CloudAPI":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- Device login ------------------------------------------------------------------

    def start_device_login(self) -> DeviceAuthorization:
        response = self._send("POST", "/auth/cli/device")
        if response.status_code != 200:
            raise APIError("Could not start the login: " + _problem_detail(response), status_code=response.status_code)
        data = response.json()
        return DeviceAuthorization(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data["verification_uri"],
            verification_uri_complete=data.get("verification_uri_complete"),
            expires_in=int(data.get("expires_in") or 300),
            interval=int(data.get("interval") or 5),
        )

    def wait_for_device_login(
        self,
        device: DeviceAuthorization,
        sleep: Optional[Callable[[float], None]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> Credentials:
        """Poll until the user approves, denies or lets the code expire (RFC 8628 section 3.5)."""
        sleep = sleep or time.sleep
        clock = clock or time.monotonic
        interval = float(device.interval)
        deadline = clock() + device.expires_in
        while clock() < deadline:
            sleep(interval)
            response = self._send("POST", "/auth/cli/token", json={"device_code": device.device_code})
            if response.status_code == 200:
                data = response.json()
                return Credentials(
                    api_url=self.api_url,
                    access_token=data["access_token"],
                    refresh_token=data["refresh_token"],
                    organization_id=data.get("organization_id"),
                    email=data.get("email"),
                )
            error = _oauth_error(response)
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error == "access_denied":
                raise CLIError("The login was denied in the browser.")
            if error == "expired_token":
                break
            raise APIError("The login failed: " + _problem_detail(response), status_code=response.status_code)
        raise CLIError("The login code expired before it was approved.", hint="Run `agno login` again.")

    # -- Operating systems --------------------------------------------------------------

    def list_operating_systems(self) -> List[RegisteredOS]:
        response = self._authed("GET", "/operating-systems/")
        if response.status_code != 200:
            raise APIError(
                "Could not list your AgentOS instances: " + _problem_detail(response),
                status_code=response.status_code,
            )
        return [RegisteredOS.from_dict(item) for item in response.json() if isinstance(item, dict)]

    def find_operating_system(self, endpoint_url: str) -> Optional[RegisteredOS]:
        target = normalize_url(endpoint_url)
        for registered in self.list_operating_systems():
            if normalize_url(registered.endpoint_url) == target:
                return registered
        return None

    def create_operating_system(self, name: str, endpoint_url: str) -> RegisteredOS:
        response = self._authed(
            "POST",
            "/operating-systems/",
            json={"name": name, "endpoint_url": endpoint_url, "enabled_jwt": True},
        )
        if response.status_code != 201:
            raise APIError(
                "Could not register " + endpoint_url + ": " + _problem_detail(response),
                status_code=response.status_code,
                hint=BILLING_HINT if response.status_code == 402 else None,
            )
        return RegisteredOS.from_dict(response.json())

    def jwks_url(self, os_id: str) -> str:
        response = self._authed("GET", "/operating-systems/" + os_id + "/jwt-config")
        if response.status_code != 200:
            raise APIError(
                "Could not read the JWT configuration: " + _problem_detail(response),
                status_code=response.status_code,
            )
        return response.json()["jwks_url"]

    def admin_token(self, os_id: str) -> str:
        """A short-lived JWT for the AgentOS carrying the signed-in user's scopes."""
        response = self._authed("GET", "/auth/sdk-token", params={"os_id": os_id})
        if response.status_code != 200:
            raise APIError(
                "Could not get a token for this AgentOS: " + _problem_detail(response),
                status_code=response.status_code,
                hint=BILLING_HINT if response.status_code == 402 else None,
            )
        return response.json()["token"]

    # -- Internals ------------------------------------------------------------------------

    def _send(self, method: str, path: str, headers: Optional[Dict[str, str]] = None, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, path, headers=headers or {}, **kwargs)
        except httpx.HTTPError as e:
            raise APIError("Could not reach " + self.api_url + ": " + str(e)) from e

    def _authed(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self.credentials is None:
            raise CLIError("You are not signed in to " + CLOUD_APP_URL + ".", hint=LOGIN_HINT)
        response = self._send(method, path, headers=self._bearer(), **kwargs)
        if response.status_code == 401:
            self._refresh()
            response = self._send(method, path, headers=self._bearer(), **kwargs)
            if response.status_code == 401:
                raise APIError("Your login was rejected.", status_code=401, hint=LOGIN_HINT)
        return response

    def _bearer(self) -> Dict[str, str]:
        assert self.credentials is not None
        return {"Authorization": "Bearer " + self.credentials.access_token}

    def _refresh(self) -> None:
        assert self.credentials is not None
        response = self._send(
            "POST",
            "/auth/cli/refresh",
            json={
                "refresh_token": self.credentials.refresh_token,
                "organization_id": self.credentials.organization_id,
            },
        )
        if response.status_code != 200:
            raise CLIError("Your login has expired.", hint=LOGIN_HINT)
        data = response.json()
        self.credentials.access_token = data["access_token"]
        self.credentials.refresh_token = data["refresh_token"]
        save_credentials(self.credentials)
