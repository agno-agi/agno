"""Fallback model switching for agent resilience.

Provides sync and async helpers that try a primary model and, on provider
errors, iterate through a list of fallback models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError, ModelRateLimitError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_info, log_warning

if TYPE_CHECKING:
    from agno.compression.manager import CompressionManager
    from agno.run.agent import RunOutput
    from agno.tools.function import Function


def try_with_fallback(
    *,
    primary_model: Model,
    fallback_models: List[Model],
    messages: List[Message],
    tools: Optional[List[Union["Function", dict]]] = None,
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    tool_call_limit: Optional[int] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    run_response: Optional["RunOutput"] = None,
    send_media_to_model: bool = True,
    compression_manager: Optional["CompressionManager"] = None,
    on_fallback: Optional[Callable] = None,
) -> ModelResponse:
    """Try the primary model, falling back to alternatives on provider errors.

    Args:
        primary_model: The primary model to try first.
        fallback_models: Ordered list of fallback models.
        messages: Messages to send to the model.
        tools: Tools available for the model.
        tool_choice: Tool choice configuration.
        tool_call_limit: Maximum number of tool calls.
        response_format: Response format specification.
        run_response: Current run response for context.
        send_media_to_model: Whether to send media to the model.
        compression_manager: Optional compression manager.
        on_fallback: Optional callback invoked with (failed_model, fallback_model, error).

    Returns:
        ModelResponse from the first model that succeeds.

    Raises:
        ModelProviderError: If all models fail.
    """
    all_models = [primary_model] + list(fallback_models)
    last_error: Optional[Exception] = None

    for i, model in enumerate(all_models):
        try:
            response = model.response(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                tool_call_limit=tool_call_limit,
                response_format=response_format,
                run_response=run_response,
                send_media_to_model=send_media_to_model,
                compression_manager=compression_manager,
            )
            if i > 0:
                log_info(f"Fallback model succeeded: {model.__class__.__name__}")
            return response
        except (ModelProviderError, ModelRateLimitError) as e:
            last_error = e
            failed_model = model
            if i < len(all_models) - 1:
                next_model = all_models[i + 1]
                log_warning(
                    f"Model {model.__class__.__name__} failed: {e}. "
                    f"Falling back to {next_model.__class__.__name__}"
                )
                if on_fallback is not None:
                    try:
                        on_fallback(failed_model, next_model, e)
                    except Exception:
                        pass  # Don't let callback errors break the fallback chain

    # All models failed — raise the last error
    raise last_error  # type: ignore[misc]


async def atry_with_fallback(
    *,
    primary_model: Model,
    fallback_models: List[Model],
    messages: List[Message],
    tools: Optional[List[Union["Function", dict]]] = None,
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    tool_call_limit: Optional[int] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    run_response: Optional["RunOutput"] = None,
    send_media_to_model: bool = True,
    compression_manager: Optional["CompressionManager"] = None,
    on_fallback: Optional[Callable] = None,
) -> ModelResponse:
    """Async variant of try_with_fallback.

    Args:
        primary_model: The primary model to try first.
        fallback_models: Ordered list of fallback models.
        messages: Messages to send to the model.
        tools: Tools available for the model.
        tool_choice: Tool choice configuration.
        tool_call_limit: Maximum number of tool calls.
        response_format: Response format specification.
        run_response: Current run response for context.
        send_media_to_model: Whether to send media to the model.
        compression_manager: Optional compression manager.
        on_fallback: Optional callback invoked with (failed_model, fallback_model, error).

    Returns:
        ModelResponse from the first model that succeeds.

    Raises:
        ModelProviderError: If all models fail.
    """
    all_models = [primary_model] + list(fallback_models)
    last_error: Optional[Exception] = None

    for i, model in enumerate(all_models):
        try:
            response = await model.aresponse(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                tool_call_limit=tool_call_limit,
                response_format=response_format,
                run_response=run_response,
                send_media_to_model=send_media_to_model,
                compression_manager=compression_manager,
            )
            if i > 0:
                log_info(f"Fallback model succeeded: {model.__class__.__name__}")
            return response
        except (ModelProviderError, ModelRateLimitError) as e:
            last_error = e
            failed_model = model
            if i < len(all_models) - 1:
                next_model = all_models[i + 1]
                log_warning(
                    f"Model {model.__class__.__name__} failed: {e}. "
                    f"Falling back to {next_model.__class__.__name__}"
                )
                if on_fallback is not None:
                    try:
                        on_fallback(failed_model, next_model, e)
                    except Exception:
                        pass

    raise last_error  # type: ignore[misc]
