from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Type, Union

from pydantic import BaseModel

from agno.compression.prompts import DEFAULT_TOOL_COMPRESSION_PROMPT
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from agno.compression.manager import CompressionManager


# --- Threshold / Selection ---


def get_tool_messages_to_compress(
    manager: CompressionManager,
    messages: List[Message],
    tools: Optional[List],
    response_format: Optional[Union[Dict, Type[BaseModel]]],
) -> List[Message]:
    """Returns tool messages to compress, or empty list if below threshold."""
    uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
    if not uncompressed:
        return []

    if manager.compress_tools_token_limit is not None and manager.model is not None:
        if manager.model.count_tokens(messages, tools, response_format) >= manager.compress_tools_token_limit:
            return uncompressed

    if manager.compress_tools_limit is not None:
        if len(uncompressed) >= manager.compress_tools_limit:
            return uncompressed

    return []


async def aget_tool_messages_to_compress(
    manager: CompressionManager,
    messages: List[Message],
    tools: Optional[List],
    response_format: Optional[Union[Dict, Type[BaseModel]]],
) -> List[Message]:
    """Async version of get_tool_messages_to_compress."""
    uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
    if not uncompressed:
        return []

    if manager.compress_tools_token_limit is not None and manager.model is not None:
        if await manager.model.acount_tokens(messages, tools, response_format) >= manager.compress_tools_token_limit:
            return uncompressed

    if manager.compress_tools_limit is not None:
        if len(uncompressed) >= manager.compress_tools_limit:
            return uncompressed

    return []


# --- Compression Execution ---


def compress_tool_results(
    manager: CompressionManager,
    messages: List[Message],
    run_metrics: Optional[RunMetrics],
) -> None:
    """Compress tool results. Mutates messages in-place."""
    prompt = manager.compress_tools_instructions or DEFAULT_TOOL_COMPRESSION_PROMPT

    for msg in messages:
        original_len = len(str(msg.content)) if msg.content else 0
        compressed = _call_llm(manager.model, prompt, f"Tool: {msg.tool_name or 'unknown'}\n{msg.content}", run_metrics)

        if compressed:
            msg.compressed_content = compressed
            _track_stat(manager.stats, "tool_results_compressed", len(msg.tool_calls) if msg.tool_calls else 1)
            _track_stat(manager.stats, "original_size", original_len)
            _track_stat(manager.stats, "compressed_size", len(compressed))
        else:
            log_warning(f"Tool compression failed for {msg.tool_name}")


async def acompress_tool_results(
    manager: CompressionManager,
    messages: List[Message],
    run_metrics: Optional[RunMetrics],
) -> None:
    """Async compress tool results with parallel LLM calls."""
    prompt = manager.compress_tools_instructions or DEFAULT_TOOL_COMPRESSION_PROMPT

    async def compress_one(msg: Message) -> Tuple[Message, Optional[str], int]:
        original_len = len(str(msg.content)) if msg.content else 0
        compressed = await _acall_llm(
            manager.model, prompt, f"Tool: {msg.tool_name or 'unknown'}\n{msg.content}", run_metrics
        )
        return msg, compressed, original_len

    results = await asyncio.gather(*[compress_one(m) for m in messages])

    for msg, compressed, original_len in results:
        if compressed:
            msg.compressed_content = compressed
            _track_stat(manager.stats, "tool_results_compressed", len(msg.tool_calls) if msg.tool_calls else 1)
            _track_stat(manager.stats, "original_size", original_len)
            _track_stat(manager.stats, "compressed_size", len(compressed))
        else:
            log_warning(f"Tool compression failed for {msg.tool_name}")


def _call_llm(model: Model, system_prompt: str, user_content: str, run_metrics: Optional[RunMetrics]) -> Optional[str]:
    try:
        response = model.response(
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_content),
            ]
        )
        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)
        return response.content
    except Exception as e:
        log_error(f"Tool compression LLM call failed: {e}")
        return None


async def _acall_llm(
    model: Model, system_prompt: str, user_content: str, run_metrics: Optional[RunMetrics]
) -> Optional[str]:
    try:
        response = await model.aresponse(
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_content),
            ]
        )
        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)
        return response.content
    except Exception as e:
        log_error(f"Tool compression LLM call failed: {e}")
        return None


def _track_stat(stats: dict, key: str, value: int) -> None:
    stats[key] = stats.get(key, 0) + value
