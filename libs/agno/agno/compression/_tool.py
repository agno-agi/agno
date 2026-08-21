"""Internal tool result compaction helpers."""

import asyncio
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics

DEFAULT_TOOL_COMPACTION_PROMPT = dedent("""\
    You are compacting tool call results to save context space while preserving critical information.

    Your goal: Extract only the essential information from the tool output.

    ALWAYS PRESERVE:
    - Specific facts: numbers, statistics, amounts, prices, quantities, metrics
    - Temporal data: dates, times, timestamps (use short format: "Oct 21 2025")
    - Entities: people, companies, products, locations, organizations
    - Identifiers: URLs, IDs, codes, technical identifiers, versions
    - Key quotes, citations, sources (if relevant to agent's task)

    COMPRESS TO ESSENTIALS:
    - Descriptions: keep only key attributes
    - Explanations: distill to core insight
    - Lists: focus on most relevant items based on agent context
    - Background: minimal context only if critical

    REMOVE ENTIRELY:
    - Introductions, conclusions, transitions
    - Hedging language ("might", "possibly", "appears to")
    - Meta-commentary ("According to", "The results show")
    - Formatting artifacts (markdown, HTML, JSON structure)
    - Redundant or repetitive information
    - Generic background not relevant to agent's task
    - Promotional language, filler words

    EXAMPLE:
    Input: "According to recent market analysis and industry reports, OpenAI has made several significant announcements in the technology sector. The company revealed ChatGPT Atlas on October 21, 2025, which represents a new AI-powered browser application that has been specifically designed for macOS users. This browser is strategically positioned to compete with traditional search engines in the market. Additionally, on October 6, 2025, OpenAI launched Apps in ChatGPT, which includes a comprehensive software development kit (SDK) for developers. The company has also announced several initial strategic partners who will be integrating with this new feature, including well-known companies such as Spotify, the popular music streaming service, Zillow, which is a real estate marketplace platform, and Canva, a graphic design platform."

    Output: "OpenAI - Oct 21 2025: ChatGPT Atlas (AI browser, macOS, search competitor); Oct 6 2025: Apps in ChatGPT + SDK; Partners: Spotify, Zillow, Canva"

    Be concise while retaining all critical facts.
    """)


def _is_tool_result_message(msg: Message) -> bool:
    return msg.role == "tool"


def should_compact_tools(
    messages: List[Message],
    compact_tools: bool,
    compact_tools_limit: Optional[int],
    compact_tools_token_limit: Optional[int],
    tools: Optional[List] = None,
    model: Optional[Model] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
) -> bool:
    """Check if tool results should be compacted."""
    if not compact_tools:
        return False

    # Token-based threshold check
    if compact_tools_token_limit is not None and model is not None:
        tokens = model.count_tokens(messages, tools, response_format)
        if tokens >= compact_tools_token_limit:
            log_info(f"Token limit hit: {tokens} >= {compact_tools_token_limit}")
            return True

    # Count-based threshold check
    if compact_tools_limit is not None:
        uncompressed_count = len([m for m in messages if _is_tool_result_message(m) and m.compressed_content is None])
        if uncompressed_count >= compact_tools_limit:
            log_info(f"Tool count limit hit: {uncompressed_count} >= {compact_tools_limit}")
            return True

    return False


async def ashould_compact_tools(
    messages: List[Message],
    compact_tools: bool,
    compact_tools_limit: Optional[int],
    compact_tools_token_limit: Optional[int],
    tools: Optional[List] = None,
    model: Optional[Model] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
) -> bool:
    """Async check if tool results should be compacted."""
    if not compact_tools:
        return False

    if compact_tools_token_limit is not None and model is not None:
        tokens = await model.acount_tokens(messages, tools, response_format)
        if tokens >= compact_tools_token_limit:
            log_info(f"Token limit hit: {tokens} >= {compact_tools_token_limit}")
            return True

    if compact_tools_limit is not None:
        uncompressed_count = len([m for m in messages if _is_tool_result_message(m) and m.compressed_content is None])
        if uncompressed_count >= compact_tools_limit:
            log_info(f"Tool count limit hit: {uncompressed_count} >= {compact_tools_limit}")
            return True

    return False


def _compact_single_tool_result(
    tool_result: Message,
    model: Optional[Model],
    instructions: Optional[str] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[str]:
    """Compress a single tool result message."""
    if not tool_result:
        return None

    tool_content = f"Tool: {tool_result.tool_name or 'unknown'}\n{tool_result.content}"

    resolved_model = get_model(model)
    if not resolved_model:
        log_warning("No compaction model available")
        return None

    prompt = instructions or DEFAULT_TOOL_COMPACTION_PROMPT
    user_message = "Tool Results to Compress: " + tool_content + "\n"

    try:
        response = resolved_model.response(
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=user_message),
            ]
        )

        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, resolved_model, ModelType.COMPRESSION_MODEL, run_metrics)

        return response.content
    except Exception as e:
        log_error(f"Error compacting tool result: {str(e)}")
        return tool_content


async def _acompact_single_tool_result(
    tool_result: Message,
    model: Optional[Model],
    instructions: Optional[str] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> Optional[str]:
    """Async compress a single tool result message."""
    if not tool_result:
        return None

    tool_content = f"Tool: {tool_result.tool_name or 'unknown'}\n{tool_result.content}"

    resolved_model = get_model(model)
    if not resolved_model:
        log_warning("No compaction model available")
        return None

    prompt = instructions or DEFAULT_TOOL_COMPACTION_PROMPT
    user_message = "Tool Results to Compress: " + tool_content + "\n"

    try:
        response = await resolved_model.aresponse(
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=user_message),
            ]
        )

        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, resolved_model, ModelType.COMPRESSION_MODEL, run_metrics)

        return response.content
    except Exception as e:
        log_error(f"Error compacting tool result: {str(e)}")
        return tool_content


def compact_tools(
    messages: List[Message],
    model: Optional[Model],
    compact_tools_enabled: bool = True,
    instructions: Optional[str] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> Dict[str, Any]:
    """Compress uncompressed tool results. Returns stats dict."""
    stats: Dict[str, Any] = {}

    if not compact_tools_enabled:
        return stats

    uncompressed = [msg for msg in messages if msg.role == "tool" and msg.compressed_content is None]
    if not uncompressed:
        return stats

    for tool_msg in uncompressed:
        original_len = len(str(tool_msg.content)) if tool_msg.content else 0
        compressed = _compact_single_tool_result(tool_msg, model, instructions, run_metrics)

        if compressed:
            tool_msg.compressed_content = compressed
            tool_count = len(tool_msg.tool_calls) if tool_msg.tool_calls else 1
            stats["tool_results_compressed"] = stats.get("tool_results_compressed", 0) + tool_count
            stats["original_size"] = stats.get("original_size", 0) + original_len
            stats["compressed_size"] = stats.get("compressed_size", 0) + len(compressed)
        else:
            log_warning(f"Compaction failed for {tool_msg.tool_name}")

    return stats


async def acompact_tools(
    messages: List[Message],
    model: Optional[Model],
    compact_tools_enabled: bool = True,
    instructions: Optional[str] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> Dict[str, Any]:
    """Async compress uncompressed tool results. Returns stats dict."""
    stats: Dict[str, Any] = {}

    if not compact_tools_enabled:
        return stats

    uncompressed = [msg for msg in messages if msg.role == "tool" and msg.compressed_content is None]
    if not uncompressed:
        return stats

    original_sizes = [len(str(msg.content)) if msg.content else 0 for msg in uncompressed]

    tasks = [_acompact_single_tool_result(msg, model, instructions, run_metrics) for msg in uncompressed]
    results = await asyncio.gather(*tasks)

    for msg, compressed, original_len in zip(uncompressed, results, original_sizes):
        if compressed:
            msg.compressed_content = compressed
            tool_count = len(msg.tool_calls) if msg.tool_calls else 1
            stats["tool_results_compressed"] = stats.get("tool_results_compressed", 0) + tool_count
            stats["original_size"] = stats.get("original_size", 0) + original_len
            stats["compressed_size"] = stats.get("compressed_size", 0) + len(compressed)
        else:
            log_warning(f"Compaction failed for {msg.tool_name}")

    return stats
