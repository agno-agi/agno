from os import getenv
from typing import Dict, Mapping, Optional

import httpx

from agno.exceptions import AgnoError, ModelAuthenticationError, ModelProviderError, ModelRateLimitError

DEFAULT_SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
SILICONFLOW_API_KEY_ENV_VAR = "SILICONFLOW_API_KEY"
SILICONFLOW_PROVIDER_NAME = "Siliconflow"


def get_siliconflow_api_key(api_key: Optional[str]) -> str:
    resolved_api_key = api_key or getenv(SILICONFLOW_API_KEY_ENV_VAR)
    if not resolved_api_key:
        raise ModelAuthenticationError(
            message=(
                "SILICONFLOW_API_KEY not set. Please set the SILICONFLOW_API_KEY environment variable or pass api_key."
            ),
            model_name=SILICONFLOW_PROVIDER_NAME,
        )
    return resolved_api_key


def get_siliconflow_headers(
    api_key: Optional[str], extra_headers: Optional[Mapping[str, str]] = None
) -> Dict[str, str]:
    headers = dict(extra_headers or {})
    headers.update(
        {
            "Authorization": f"Bearer {get_siliconflow_api_key(api_key)}",
            "Content-Type": "application/json",
        }
    )
    return headers


def get_siliconflow_url(base_url: str, endpoint: str) -> str:
    return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"


def get_siliconflow_trace_id(response: httpx.Response) -> Optional[str]:
    return response.headers.get("x-siliconcloud-trace-id")


def _get_error_message(response: httpx.Response) -> str:
    message: Optional[str] = None
    try:
        response_body = response.json()
        if isinstance(response_body, dict):
            error = response_body.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                message = error["message"]
            elif isinstance(error, str):
                message = error
            elif isinstance(response_body.get("message"), str):
                message = response_body["message"]
    except ValueError:
        pass

    if not message:
        message = response.reason_phrase or "Unknown provider error"

    trace_id = get_siliconflow_trace_id(response)
    trace_suffix = f" (trace ID: {trace_id})" if trace_id else ""
    return f"Siliconflow API request failed with status {response.status_code}: {message}{trace_suffix}"


def raise_for_siliconflow_status(response: httpx.Response, model_id: str) -> None:
    if response.is_success:
        return

    message = _get_error_message(response)
    if response.status_code in {401, 403}:
        raise ModelAuthenticationError(
            message=message,
            status_code=response.status_code,
            model_name=SILICONFLOW_PROVIDER_NAME,
        )
    if response.status_code in {429, 529}:
        raise ModelRateLimitError(
            message=message,
            status_code=response.status_code,
            model_name=SILICONFLOW_PROVIDER_NAME,
            model_id=model_id,
        )
    raise ModelProviderError(
        message=message,
        status_code=response.status_code,
        model_name=SILICONFLOW_PROVIDER_NAME,
        model_id=model_id,
    )


def get_siliconflow_request_error(error: Exception, model_id: str) -> AgnoError:
    if isinstance(error, AgnoError):
        return error

    if isinstance(error, httpx.TimeoutException):
        message = "Siliconflow API request timed out"
        status_code = 504
    elif isinstance(error, httpx.RequestError):
        message = "Siliconflow API request failed due to a network error"
        status_code = 503
    else:
        message = "Siliconflow API returned a malformed response"
        status_code = 502

    return ModelProviderError(
        message=message,
        status_code=status_code,
        model_name=SILICONFLOW_PROVIDER_NAME,
        model_id=model_id,
    )


def get_malformed_siliconflow_response_error(
    message: str, model_id: str, trace_id: Optional[str] = None
) -> ModelProviderError:
    trace_suffix = f" (trace ID: {trace_id})" if trace_id else ""
    return ModelProviderError(
        message=f"Siliconflow API returned a malformed response: {message}{trace_suffix}",
        status_code=502,
        model_name=SILICONFLOW_PROVIDER_NAME,
        model_id=model_id,
    )
