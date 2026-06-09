from typing import Dict

from httpx import AsyncClient as HttpxAsyncClient
from httpx import Client as HttpxClient
from httpx import Response

from agno.api.settings import agno_api_settings

TELEMETRY_TIMEOUT = 5  # seconds — telemetry must never block the main flow


class Api:
    def __init__(self):
        self.headers: Dict[str, str] = {
            "user-agent": f"{agno_api_settings.app_name}/{agno_api_settings.app_version}",
            "Content-Type": "application/json",
        }

    def Client(self) -> HttpxClient:
        return HttpxClient(
            base_url=agno_api_settings.api_url,
            headers=self.headers,
            timeout=60,
            http2=True,
        )

    def AsyncClient(self) -> HttpxAsyncClient:
        return HttpxAsyncClient(
            base_url=agno_api_settings.api_url,
            headers=self.headers,
            timeout=60,
            http2=True,
        )

    def TelemetryClient(self) -> HttpxClient:
        """Short-timeout client for fire-and-forget telemetry POSTs."""
        return HttpxClient(
            base_url=agno_api_settings.api_url,
            headers=self.headers,
            timeout=TELEMETRY_TIMEOUT,
            http2=True,
        )

    def AsyncTelemetryClient(self) -> HttpxAsyncClient:
        """Short-timeout async client for fire-and-forget telemetry POSTs."""
        return HttpxAsyncClient(
            base_url=agno_api_settings.api_url,
            headers=self.headers,
            timeout=TELEMETRY_TIMEOUT,
            http2=True,
        )


api = Api()


def invalid_response(r: Response) -> bool:
    """Returns true if the response is invalid"""

    if r.status_code >= 400:
        return True
    return False
