import json
from typing import Any, Dict, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`")


class CustomApiTools(Toolkit):
    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        verify_ssl: bool = True,
        timeout: int = 30,
        make_request: bool = True,
        **kwargs,
    ):
        super().__init__(name="api_tools", **kwargs)

        self.base_url = base_url
        self.username = username
        self.password = password
        self.api_key = api_key
        self.default_headers = headers or {}
        self.verify_ssl = verify_ssl
        self.timeout = timeout

        if make_request:
            self.register(self.make_request)

    def _get_auth(self) -> Optional[HTTPBasicAuth]:
        """Get authentication object if credentials are provided."""
        if self.username and self.password:
            return HTTPBasicAuth(self.username, self.password)
        return None

    def _get_headers(self, additional_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Combine default headers with additional headers."""
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
            method (str): HTTP method (GET, POST, PUT, DELETE, PATCH)
            endpoint (str): API endpoint (will be combined with base_url if set)
            params (Optional[Dict[str, Any]]): Query parameters
            data (Optional[Dict[str, Any]]): Form data to send
            headers (Optional[Dict[str, str]]): Additional headers
            json_data (Optional[Dict[str, Any]]): JSON data to send

        Returns:
            str: JSON string containing response data or error message
        """
        try:
            url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}" if self.base_url else endpoint
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

            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "data": response_data,
            }

            if not response.ok:
                logger.error(f"Request failed with status {response.status_code}: {response.text}")
                result["error"] = "Request failed"

            return json.dumps(result, indent=2)

        except requests.exceptions.RequestException as e:
            error_message = f"Request failed: {str(e)}"
            logger.error(error_message)
            return json.dumps({"error": error_message}, indent=2)
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            logger.error(error_message)
            return json.dumps({"error": error_message}, indent=2)
