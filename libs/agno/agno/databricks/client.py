import random
from contextlib import contextmanager
from time import sleep
from typing import Any, Dict, Optional

import httpx

from agno.databricks.auth import build_databricks_headers
from agno.databricks.errors import map_databricks_request_error, raise_for_databricks_response
from agno.databricks.settings import DatabricksSettings
from agno.databricks.utils import RETRYABLE_STATUS_CODES, build_url, merge_headers
from agno.utils.http import get_default_sync_client
from agno.utils.log import log_warning


class DatabricksClient:
    def __init__(
        self,
        *,
        settings: Optional[DatabricksSettings] = None,
        host: Optional[str] = None,
        workspace_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        default_headers: Optional[Dict[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        if settings is not None:
            self.settings = settings
        elif any(value is not None for value in [host, workspace_url, token, timeout, max_retries, default_headers]):
            self.settings = DatabricksSettings.from_values(
                host=host,
                workspace_url=workspace_url,
                token=token,
                timeout=timeout if timeout is not None else 60.0,
                max_retries=max_retries if max_retries is not None else 3,
                default_headers=default_headers or {},
            )
        else:
            self.settings = DatabricksSettings()
        self.http_client = http_client

    @property
    def base_url(self) -> str:
        if not self.settings.base_url:
            raise ValueError("Databricks host is required before making requests")
        return self.settings.base_url

    def _get_client(self) -> httpx.Client:
        return self.http_client or get_default_sync_client()

    def _get_headers(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        merged = merge_headers(self.settings.default_headers, headers)
        return build_databricks_headers(
            token=self.settings.token,
            headers=merged,
            user_agent=self.settings.user_agent,
        )

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
    ) -> httpx.Response:
        request_url = build_url(self.base_url, endpoint)
        request_timeout = timeout if timeout is not None else self.settings.timeout
        attempts = max(1, (retries if retries is not None else self.settings.max_retries) + 1)
        request_headers = self._get_headers(headers)
        operation = f"{method.upper()} {endpoint}"

        for attempt in range(attempts):
            try:
                response = self._get_client().request(
                    method=method,
                    url=request_url,
                    params=params,
                    json=json,
                    data=data,
                    headers=request_headers,
                    timeout=request_timeout,
                )

                if response.status_code in RETRYABLE_STATUS_CODES and attempt < attempts - 1:
                    wait_seconds = 2**attempt + random.uniform(0, 0.5)
                    log_warning(f"{operation} returned {response.status_code}; retrying in {wait_seconds} seconds")
                    sleep(wait_seconds)
                    continue

                raise_for_databricks_response(response, operation=operation)
                return response
            except httpx.RequestError as exc:
                if attempt < attempts - 1:
                    wait_seconds = 2**attempt + random.uniform(0, 0.5)
                    log_warning(f"{operation} failed with a network error; retrying in {wait_seconds} seconds")
                    sleep(wait_seconds)
                    continue

                raise map_databricks_request_error(exc, operation=operation, base_url=self.base_url) from exc

        raise RuntimeError(f"Databricks request loop exited unexpectedly for {operation}")

    def request_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
    ) -> Any:
        response = self.request(
            method,
            endpoint,
            params=params,
            json=json,
            data=data,
            headers=headers,
            timeout=timeout,
            retries=retries,
        )

        if not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            log_warning("Databricks response is not valid JSON; falling back to raw text")
            return response.text

    @contextmanager
    def stream(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ):
        """Stream an HTTP response from Databricks.

        No retry logic is applied to streaming requests because once a streaming
        response begins, partial consumption makes safe retries impossible.
        """
        request_url = build_url(self.base_url, endpoint)
        request_timeout = timeout if timeout is not None else self.settings.timeout
        request_headers = self._get_headers(headers)
        operation = f"{method.upper()} {endpoint}"

        try:
            with self._get_client().stream(
                method=method,
                url=request_url,
                params=params,
                json=json,
                data=data,
                headers=request_headers,
                timeout=request_timeout,
            ) as response:
                if response.status_code >= 400:
                    response.read()
                raise_for_databricks_response(response, operation=operation)
                yield response
        except httpx.RequestError as exc:
            raise map_databricks_request_error(exc, operation=operation, base_url=self.base_url) from exc
