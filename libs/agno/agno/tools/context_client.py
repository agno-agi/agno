import json
from typing import Any, Dict, Optional

import httpx


class ContextClient:
    def __init__(
        self,
        api_key: Optional[str],
        base_url: str,
        timeout: int,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, params: Dict[str, Any]) -> str:
        try:
            response = httpx.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            return self._serialize_response(response)
        except httpx.RequestError as error:
            return self._serialize_connection_error(error)

    async def aget(self, path: str, params: Dict[str, Any]) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    params=params,
                )
            return self._serialize_response(response)
        except httpx.RequestError as error:
            return self._serialize_connection_error(error)

    def post(self, path: str, payload: Dict[str, Any]) -> str:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            return self._serialize_response(response)
        except httpx.RequestError as error:
            return self._serialize_connection_error(error)

    async def apost(self, path: str, payload: Dict[str, Any]) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    json=payload,
                )
            return self._serialize_response(response)
        except httpx.RequestError as error:
            return self._serialize_connection_error(error)

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ValueError("CONTEXT_API_KEY is required to use Context.dev tools")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _serialize_response(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            data = {"message": response.text or "Context.dev returned a non-JSON response"}

        if response.is_success:
            return json.dumps(data, ensure_ascii=False, default=str)

        return json.dumps(
            {
                "error": "Context.dev API request failed",
                "status_code": response.status_code,
                "details": data,
            },
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _serialize_connection_error(error: httpx.RequestError) -> str:
        return json.dumps(
            {
                "error": "Could not connect to Context.dev",
                "details": str(error),
            },
            ensure_ascii=False,
        )
