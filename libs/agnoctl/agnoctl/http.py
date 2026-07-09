"""Thin HTTP client for the AgentOS REST API.

This module talks plain HTTP to a running AgentOS. It deliberately does not import the
agno framework: the CLI must stay installable and fast under `uvx` with nothing but
httpx, rich, and typer.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

import httpx

from agnoctl import __version__
from agnoctl.errors import APIError, ConflictError

# Test hook: tests set this to an httpx.MockTransport so every client in the CLI
# (API, discovery, MCP verification) talks to an in-memory fake AgentOS.
_transport_override: Optional[httpx.BaseTransport] = None

DEFAULT_TIMEOUT = 10.0


def build_client(base_url: str = "", timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        timeout=timeout,
        transport=_transport_override,
        headers={"user-agent": "agnoctl/" + __version__},
        follow_redirects=True,
    )


@dataclass
class ServiceAccount:
    id: str
    name: str
    principal: str
    token_prefix: str
    scopes: List[str] = field(default_factory=list)
    created_at: Optional[int] = None
    expires_at: Optional[int] = None
    last_used_at: Optional[int] = None
    revoked_at: Optional[int] = None
    created_by: Optional[str] = None
    # Present only on the create response; never persisted by the CLI.
    token: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceAccount":
        # Servers send scopes as parsed RBAC objects ({raw, namespace, ...}) or as
        # plain strings; keep the raw string either way.
        return cls(
            id=data["id"],
            name=data["name"],
            principal=data.get("principal") or "sa:" + data["name"],
            token_prefix=data.get("token_prefix") or "",
            scopes=[s if isinstance(s, str) else s.get("raw", "") for s in data.get("scopes") or []],
            created_at=data.get("created_at"),
            expires_at=data.get("expires_at"),
            last_used_at=data.get("last_used_at"),
            revoked_at=data.get("revoked_at"),
            created_by=data.get("created_by"),
            token=data.get("token"),
        )

    def public_dict(self) -> Dict[str, Any]:
        """The account as a JSON-safe dict, always excluding the plaintext token."""
        return {
            "id": self.id,
            "name": self.name,
            "principal": self.principal,
            "token_prefix": self.token_prefix,
            "scopes": self.scopes,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_used_at": self.last_used_at,
            "revoked_at": self.revoked_at,
        }


def _error_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
        if isinstance(detail, str) and detail:
            return detail
        # FastAPI validation errors (422) ship a list of error objects. Surfacing the
        # first message beats an opaque "HTTP 422" -- e.g. a payload-shape skew between
        # this CLI and an older/newer server is otherwise undiagnosable.
        if isinstance(detail, list) and detail and isinstance(detail[0], dict):
            msg = detail[0].get("msg")
            loc = detail[0].get("loc")
            if isinstance(msg, str) and msg:
                if isinstance(loc, list) and loc:
                    return msg + " (at " + ".".join(str(part) for part in loc) + ")"
                return msg
    except Exception:
        pass
    return "HTTP " + str(response.status_code)


class AgentOSAPI:
    """Sync client for the AgentOS endpoints the CLI needs.

    The CLI is a short-lived terminal process making a handful of sequential calls, so a
    sync client is the right shape; programs embedding Agno should use agno.client instead.
    """

    def __init__(self, base_url: str, admin_token: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self._client = build_client(base_url=self.base_url, timeout=timeout)

    def _headers(self) -> Dict[str, str]:
        if self.admin_token:
            return {"Authorization": "Bearer " + self.admin_token}
        return {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AgentOSAPI":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- Probes ------------------------------------------------------------------

    def health(self) -> Optional[Dict[str, Any]]:
        """GET /health. Returns the payload, or None when unreachable or not an AgentOS."""
        return self._get_json_or_none("/health")

    def info(self) -> Optional[Dict[str, Any]]:
        """GET /info (unauthenticated). Returns the payload, or None when unavailable."""
        return self._get_json_or_none("/info")

    def _get_json_or_none(self, path: str) -> Optional[Dict[str, Any]]:
        """GET a JSON object, or None when unreachable, non-200, or not a JSON object."""
        try:
            response = self._client.get(path)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def probe_auth_mode(self) -> str:
        """Detect the auth mode by probing GET /config without credentials.

        Fallback for servers whose /info predates the mcp/auth_mode discovery fields.
        The 401 detail strings are the only externally observable distinction between
        security-key mode and JWT mode on older servers.
        """
        try:
            response = self._client.get("/config")
        except httpx.HTTPError:
            return "unknown"
        if response.status_code == 200:
            return "none"
        if response.status_code == 401:
            detail = _error_detail(response)
            if "required" in detail.lower():
                return "security_key"
            return "jwt"
        return "unknown"

    # -- Service accounts ----------------------------------------------------------

    def create_service_account(
        self,
        name: str,
        scopes: Optional[List[str]] = None,
        expires_in_days: Optional[int] = None,
        never_expires: bool = False,
        allow_privileged_scopes: bool = False,
    ) -> ServiceAccount:
        body: Dict[str, Any] = {"name": name}
        if scopes:
            # The API takes the RBAC write shape ({scope, effect} objects); the CLI
            # keeps its flags as plain scope strings and converts here.
            body["scopes"] = [{"scope": scope, "effect": "allow"} for scope in scopes]
        if never_expires:
            body["never_expires"] = True
        elif expires_in_days is not None:
            body["expires_in_days"] = expires_in_days
        if allow_privileged_scopes:
            body["allow_privileged_scopes"] = True

        response = self._request("POST", "/service-accounts", json=body)
        if response.status_code == 409:
            raise ConflictError("A service account named '" + name + "' already exists.")
        if response.status_code != 201:
            raise APIError(
                "Could not create service account '" + name + "': " + _error_detail(response),
                status_code=response.status_code,
            )
        return self._parse_account(response)

    def list_service_accounts(self, include_revoked: bool = True) -> List[ServiceAccount]:
        accounts: List[ServiceAccount] = []
        for page_accounts in self._iter_service_account_pages(include_revoked=include_revoked):
            accounts.extend(page_accounts)
        return accounts

    def _iter_service_account_pages(self, include_revoked: bool = True) -> Iterator[List[ServiceAccount]]:
        page = 1
        while True:
            params: Dict[str, Any] = {"page": page, "limit": 100}
            if not include_revoked:
                params["include_revoked"] = False
            response = self._request("GET", "/service-accounts", params=params)
            if response.status_code != 200:
                raise APIError(
                    "Could not list service accounts: " + _error_detail(response),
                    status_code=response.status_code,
                )
            payload = self._parse_json(response)
            data = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(data, list):
                return
            accounts: List[ServiceAccount] = []
            for item in data:
                if isinstance(item, dict):
                    try:
                        accounts.append(ServiceAccount.from_dict(item))
                    except KeyError as e:
                        raise APIError("The AgentOS returned a malformed service account (missing " + str(e) + ").")
            yield accounts
            meta = payload.get("meta") if isinstance(payload, dict) else None
            total_pages = (meta or {}).get("total_pages") if isinstance(meta, dict) else None
            if not total_pages or page >= int(total_pages):
                return
            page += 1

    def find_service_account(self, name: str) -> Optional[ServiceAccount]:
        # Active accounts only, one page at a time, stopping at the first match --
        # token rotation grows the revoked history monotonically, so downloading the
        # full list to find one active name gets steadily more expensive.
        for page_accounts in self._iter_service_account_pages(include_revoked=False):
            for account in page_accounts:
                if account.name == name:
                    return account
        return None

    def revoke_service_account(self, account_id: str) -> None:
        response = self._request("DELETE", "/service-accounts/" + account_id)
        if response.status_code not in (200, 204):
            raise APIError(
                "Could not revoke service account: " + _error_detail(response),
                status_code=response.status_code,
            )

    # -- Internals -----------------------------------------------------------------

    def _parse_json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except Exception:
            raise APIError(
                "The server at "
                + self.base_url
                + " returned a non-JSON response (HTTP "
                + str(response.status_code)
                + ") - is this really an AgentOS?"
            )

    def _parse_account(self, response: httpx.Response) -> ServiceAccount:
        payload = self._parse_json(response)
        if not isinstance(payload, dict):
            raise APIError("The AgentOS returned an unexpected service-account payload.")
        try:
            return ServiceAccount.from_dict(payload)
        except KeyError as e:
            raise APIError("The AgentOS returned a malformed service account (missing " + str(e) + ").")

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, headers=self._headers(), **kwargs)
        except httpx.HTTPError as e:
            raise APIError("Could not reach the AgentOS at " + self.base_url + ": " + str(e)) from e
        if response.status_code in (401, 403):
            raise APIError(
                "The AgentOS rejected the admin credential (" + _error_detail(response) + ").",
                status_code=response.status_code,
                hint="Set AGNO_ADMIN_TOKEN (or OS_SECURITY_KEY) to a credential with admin access.",
            )
        return response
