import json
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Union

from agno.tools import Toolkit
from agno.tools._security import (
    redact_password,
    unwrap_secret,
    validate_public_url,
)
from agno.utils.log import log_debug, log_error, log_warning

try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`")

if TYPE_CHECKING:
    from pydantic import SecretStr


class CustomApiTools(Toolkit):
    """HTTP API toolkit.

    Security notes (hardened build):

    * Every URL is validated against an SSRF blocklist (private /
      loopback / link-local / multicast / reserved / unspecified
      addresses) before the request is issued. Set
      ``allow_private_networks=True`` for deployments that
      intentionally target intranet / VPC endpoints.
    * ``verify_ssl=False`` disables TLS certificate verification and
      exposes traffic to active MITM. Construction fails unless the
      deployer also passes ``acknowledge_mitm_risk=True``; even then
      a warning is logged.
    * ``password`` and ``api_key`` accept ``pydantic.SecretStr`` and
      are redacted from ``__repr__``.

    Args:
        base_url: Optional base URL prepended to every endpoint.
        username: Basic-auth username.
        password: Basic-auth password (``SecretStr`` recommended).
        api_key: Bearer token (``SecretStr`` recommended).
        headers: Default headers applied to every request.
        verify_ssl: Verify TLS certificates. Default True.
        acknowledge_mitm_risk: Required when ``verify_ssl=False``.
        allow_private_networks: Skip the SSRF address-class check.
        timeout: Per-request timeout in seconds.
        enable_make_request: Register :meth:`make_request`.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[Union[str, "SecretStr"]] = None,
        api_key: Optional[Union[str, "SecretStr"]] = None,
        headers: Optional[Dict[str, str]] = None,
        verify_ssl: bool = True,
        acknowledge_mitm_risk: bool = False,
        allow_private_networks: bool = False,
        timeout: int = 30,
        enable_make_request: bool = True,
        all: bool = False,
        **kwargs,
    ):
        if not verify_ssl and not acknowledge_mitm_risk:
            raise ValueError(
                "verify_ssl=False disables TLS certificate verification "
                "and allows MITM. To proceed, also pass "
                "acknowledge_mitm_risk=True."
            )
        if not verify_ssl:
            log_warning(
                "CustomApiTools: TLS certificate verification DISABLED; traffic is vulnerable to man-in-the-middle."
            )

        self.base_url: Optional[str] = base_url
        self.username: Optional[str] = username
        self.password: Optional[str] = unwrap_secret(password)
        self.api_key: Optional[str] = unwrap_secret(api_key)
        self.default_headers: Dict[str, str] = headers or {}
        self.verify_ssl: bool = verify_ssl
        self.timeout: int = timeout
        self._allow_private_networks: bool = bool(allow_private_networks)

        tools: List[Any] = []
        if all or enable_make_request:
            tools.append(self.make_request)

        super().__init__(name="api_tools", tools=tools, **kwargs)

    def __repr__(self) -> str:
        return (
            f"CustomApiTools(base_url={self.base_url!r}, "
            f"username={self.username!r}, verify_ssl={self.verify_ssl!r}, "
            f"password={redact_password(self.password)!r}, "
            f"api_key={redact_password(self.api_key)!r})"
        )

    def _get_auth(self) -> Optional[HTTPBasicAuth]:
        """Return an ``HTTPBasicAuth`` when both username and password are set."""
        if self.username and self.password:
            return HTTPBasicAuth(self.username, self.password)
        return None

    def _get_headers(self, additional_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Combine default headers with per-call additional headers."""
        headers = self.default_headers.copy()
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if additional_headers:
            headers.update(additional_headers)
        return headers

    def make_request(
        self,
        endpoint: str,
        method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Make an HTTP request to the API.

        Args:
            endpoint: API endpoint. Combined with ``base_url`` when set.
            method: HTTP method.
            params: Query parameters.
            data: Form data to send.
            headers: Additional headers merged on top of defaults.
            json_data: JSON body to send.

        Returns:
            A JSON string with ``status_code``, ``headers`` and ``data``
            on success, or an ``{"error": ...}`` payload on failure.
        """
        try:
            if self.base_url:
                url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
            else:
                url = endpoint
            try:
                validate_public_url(
                    url,
                    allow_private_networks=self._allow_private_networks,
                )
            except ValueError as e:
                log_warning(f"CustomApiTools blocked URL: {e}")
                return json.dumps({"error": str(e)}, indent=2)
            log_debug(f"Making {method} request to {url}")

            response = requests.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=self._get_headers(headers),
                auth=self._get_auth(),
                verify=self.verify_ssl,
                timeout=self.timeout,
            )

            try:
                response_data = response.json()
            except json.JSONDecodeError:
                response_data = {"text": response.text}

            result: Dict[str, Any] = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "data": response_data,
            }

            if not response.ok:
                log_error(f"Request failed with status {response.status_code}: {response.text}")
                result["error"] = "Request failed"

            return json.dumps(result, indent=2)

        except requests.exceptions.RequestException as e:
            error_message = f"Request failed: {str(e)}"
            log_error(error_message)
            return json.dumps({"error": error_message}, indent=2)
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            log_error(error_message)
            return json.dumps({"error": error_message}, indent=2)
