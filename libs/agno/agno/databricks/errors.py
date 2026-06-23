from typing import Any, Optional

import httpx

from agno.databricks.schemas import DatabricksAPIError
from agno.exceptions import AgnoError, ModelAuthenticationError, ModelProviderError, RemoteServerUnavailableError


def extract_databricks_error_message(payload: Any, fallback_message: str) -> str:
    return DatabricksAPIError.from_payload(payload).best_message(fallback_message)


def map_databricks_http_error(
    response: httpx.Response,
    *,
    operation: str = "Databricks request",
    model_name: Optional[str] = None,
    model_id: Optional[str] = None,
) -> Exception:
    payload: Any = None
    fallback_message = f"{operation} failed with status {response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    message = extract_databricks_error_message(payload, fallback_message)

    if model_name is not None or model_id is not None:
        if response.status_code in {401, 403}:
            return ModelAuthenticationError(
                message=message,
                status_code=response.status_code,
                model_name=model_name,
            )

        provider_error = ModelProviderError(
            message=message,
            status_code=response.status_code,
            model_name=model_name,
            model_id=model_id,
        )
        return ModelProviderError.classify(provider_error)

    return AgnoError(message=message, status_code=response.status_code)


def map_databricks_request_error(
    exc: Exception,
    *,
    operation: str = "Databricks request",
    base_url: Optional[str] = None,
    model_name: Optional[str] = None,
    model_id: Optional[str] = None,
) -> Exception:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException, httpx.NetworkError)):
        message = f"{operation} to Databricks failed"
        if isinstance(exc, httpx.TimeoutException):
            message = f"{operation} to Databricks timed out"

        if model_name is not None or model_id is not None:
            provider_error = ModelProviderError(
                message=message,
                status_code=503,
                model_name=model_name,
                model_id=model_id,
            )
            return ModelProviderError.classify(provider_error)

        return RemoteServerUnavailableError(
            message=message,
            base_url=base_url,
            original_error=exc,
        )

    if model_name is not None or model_id is not None:
        provider_error = ModelProviderError(
            message=str(exc),
            status_code=500,
            model_name=model_name,
            model_id=model_id,
        )
        return ModelProviderError.classify(provider_error)

    return AgnoError(message=str(exc), status_code=500)


def raise_for_databricks_response(
    response: httpx.Response,
    *,
    operation: str = "Databricks request",
    model_name: Optional[str] = None,
    model_id: Optional[str] = None,
) -> None:
    if response.status_code >= 400:
        raise map_databricks_http_error(
            response,
            operation=operation,
            model_name=model_name,
            model_id=model_id,
        )
