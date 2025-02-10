from os import getenv
from typing import Dict, Optional

from httpx import AsyncClient as HttpxAsyncClient
from httpx import Client as HttpxClient
from httpx import Response

from agno.cli.credentials import read_auth_token
from agno.cli.settings import agno_cli_settings
from agno.constants import AGNO_API_KEY_ENV_VAR
from agno.utils.log import logger


class Api:
    def __init__(self):
        self.headers: Dict[str, str] = {
            "user-agent": f"{agno_cli_settings.app_name}/{agno_cli_settings.app_version}",
            "Content-Type": "application/json",
        }
        self._auth_token: Optional[str] = None
        self._authenticated_headers = None

    @property
    def auth_token(self) -> Optional[str]:
        if self._auth_token is None:
            try:
                self._auth_token = read_auth_token()
            except Exception as e:
                logger.debug(f"Failed to read auth token: {e}")
        return self._auth_token

    @property
    def authenticated_headers(self) -> Dict[str, str]:
        if self._authenticated_headers is None:
            self._authenticated_headers = self.headers.copy()
            token = self.auth_token
            if token is not None:
                self._authenticated_headers[agno_cli_settings.auth_token_header] = token
            agno_api_key = getenv(AGNO_API_KEY_ENV_VAR)
            if agno_api_key is not None:
                self._authenticated_headers["Authorization"] = f"Bearer {agno_api_key}"
        return self._authenticated_headers

    def Client(self) -> HttpxClient:
        return HttpxClient(
            base_url=agno_cli_settings.api_url,
            headers=self.headers,
            timeout=60,
        )

    def AuthenticatedClient(self) -> HttpxClient:
        return HttpxClient(
            base_url=agno_cli_settings.api_url,
            headers=self.authenticated_headers,
            timeout=60,
        )

    def AsyncClient(self) -> HttpxAsyncClient:
        return HttpxAsyncClient(
            base_url=agno_cli_settings.api_url,
            headers=self.headers,
            timeout=60,
        )

    def AuthenticatedAsyncClient(self) -> HttpxAsyncClient:
        return HttpxAsyncClient(
            base_url=agno_cli_settings.api_url,
            headers=self.authenticated_headers,
            timeout=60,
        )


api = Api()


def invalid_response(r: Response) -> bool:
    """Returns true if the response is invalid"""

    if r.status_code >= 400:
        return True
    return False
