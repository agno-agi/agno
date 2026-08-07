"""HTTP helpers used by the Remote* classes to call the RemoteAccess interface of an AgentOS.

These helpers are private to the remote package. They intentionally do not depend on
AgentOSClient: the Remote* classes talk to the opt-in RemoteAccess interface endpoints
(e.g. /remote/agents/{agent_id}/runs) with their own thin HTTP layer.
"""

import json
from typing import Any, AsyncIterator, Callable, Dict, Optional, Sequence

from httpx import ConnectError, ConnectTimeout, TimeoutException

from agno.exceptions import RemoteServerUnavailableError
from agno.media import Audio, File, Image, Video
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import logger


def _unavailable_error(base_url: str, timeout: float, error: Exception) -> RemoteServerUnavailableError:
    if isinstance(error, (ConnectError, ConnectTimeout)):
        message = f"Failed to connect to remote server at {base_url}"
    else:
        message = f"Request to remote server at {base_url} timed out after {timeout} seconds"
    return RemoteServerUnavailableError(
        message=message,
        base_url=base_url,
        original_error=error,
    )


def build_run_form_data(
    message: str,
    stream: bool,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[Sequence[Image]] = None,
    audio: Optional[Sequence[Audio]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Build the form payload for run endpoints of the Remote interface.

    Dict kwargs (session_state, dependencies, metadata, knowledge_filters, ...) are
    serialized as JSON strings, matching what the run endpoints expect.
    """
    data: Dict[str, Any] = {"message": message, "stream": "true" if stream else "false"}
    if session_id is not None:
        data["session_id"] = session_id
    if user_id is not None:
        data["user_id"] = user_id
    if images:
        data["images"] = json.dumps([img.to_dict() for img in images])
    if audio:
        data["audio"] = json.dumps([a.to_dict() for a in audio])
    if videos:
        data["videos"] = json.dumps([v.to_dict() for v in videos])
    if files:
        # Sent as "input_files" because the run endpoints already use the "files"
        # field for multipart uploads (List[UploadFile]).
        data["input_files"] = json.dumps([f.to_dict() for f in files])

    for key, value in kwargs.items():
        if isinstance(value, dict):
            data[key] = json.dumps(value)
        else:
            data[key] = value

    return {k: v for k, v in data.items() if v is not None}


def build_continue_form_data(
    stream: bool,
    tools_field: str,
    tools: Sequence[Any],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Build the form payload for continue endpoints of the Remote interface.

    Args:
        stream: Whether the continued run should stream.
        tools_field: Name of the form field carrying the serialized tool payloads.
            Agents use "tools", teams "requirements", workflows "step_requirements".
        tools: Objects exposing to_dict() or plain dicts, serialized as a JSON list.
        session_id: Optional session ID.
        user_id: Optional user ID.
    """
    serialized = [tool.to_dict() if hasattr(tool, "to_dict") else tool for tool in tools]
    data: Dict[str, Any] = {
        tools_field: json.dumps(serialized),
        "stream": "true" if stream else "false",
    }
    if session_id is not None:
        data["session_id"] = session_id
    if user_id is not None:
        data["user_id"] = user_id

    for key, value in kwargs.items():
        if isinstance(value, dict):
            data[key] = json.dumps(value)
        else:
            data[key] = value

    return {k: v for k, v in data.items() if v is not None}


def get_json(
    base_url: str,
    path: str,
    timeout: float = 60.0,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Execute a synchronous GET request and return the parsed JSON response."""
    url = f"{base_url}{path}"
    sync_client = get_default_sync_client()
    try:
        response = sync_client.get(url, params=params, headers=headers or {}, timeout=timeout)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()
    except (ConnectError, ConnectTimeout, TimeoutException) as e:
        raise _unavailable_error(base_url, timeout, e) from e


async def aget_json(
    base_url: str,
    path: str,
    timeout: float = 60.0,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Execute an asynchronous GET request and return the parsed JSON response."""
    url = f"{base_url}{path}"
    async_client = get_default_async_client()
    try:
        response = await async_client.get(url, params=params, headers=headers or {}, timeout=timeout)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()
    except (ConnectError, ConnectTimeout, TimeoutException) as e:
        raise _unavailable_error(base_url, timeout, e) from e


async def apost_form(
    base_url: str,
    path: str,
    data: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    """Execute an asynchronous form POST request and return the parsed JSON response."""
    url = f"{base_url}{path}"
    async_client = get_default_async_client()
    kwargs: Dict[str, Any] = {"headers": headers or {}}
    if data is not None:
        kwargs["data"] = data
    try:
        response = await async_client.post(url, timeout=timeout, **kwargs)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()
    except (ConnectError, ConnectTimeout, TimeoutException) as e:
        raise _unavailable_error(base_url, timeout, e) from e


async def astream_form_events(
    base_url: str,
    path: str,
    data: Dict[str, Any],
    event_parser: Callable[[dict], Any],
    timeout: float = 60.0,
    headers: Optional[Dict[str, str]] = None,
) -> AsyncIterator[Any]:
    """Execute a streaming form POST request and yield parsed SSE events.

    Parses "data: " SSE lines into dicts and maps them through event_parser
    (e.g. run_output_event_from_dict). Malformed or unknown events are skipped.
    """
    url = f"{base_url}{path}"
    async_client = get_default_async_client()
    try:
        async with async_client.stream("POST", url, data=data, headers=headers or {}, timeout=timeout) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                # Skip empty lines and comments (SSE protocol)
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    try:
                        event_dict = json.loads(line[6:])
                        yield event_parser(event_dict)
                    except json.JSONDecodeError:
                        logger.exception(f"Failed to parse SSE JSON: {line[:100]}...")
                        continue
                    except ValueError:
                        logger.exception(f"Unknown event type: {line[:100]}...")
                        continue
    except (ConnectError, ConnectTimeout, TimeoutException) as e:
        raise _unavailable_error(base_url, timeout, e) from e
