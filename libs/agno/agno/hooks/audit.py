"""
Tool audit hook for logging all tool calls made by an agent.

Provides structured audit logging of tool executions including tool name,
arguments, results, duration, timestamps, and error information. Logs can
be written to a file, sent to a callback, or both.

Usage:
    from agno.hooks import ToolAuditHook

    # Log to file
    agent = Agent(
        tools=[...],
        tool_hooks=[ToolAuditHook(log_file="tool_audit.jsonl")],
    )

    # Log to callback
    agent = Agent(
        tools=[...],
        tool_hooks=[ToolAuditHook(callback=my_callback_fn)],
    )

    # Log to both
    agent = Agent(
        tools=[...],
        tool_hooks=[ToolAuditHook(log_file="audit.jsonl", callback=my_fn)],
    )

    # Compliance mode — block tool execution if audit fails
    agent = Agent(
        tools=[...],
        tool_hooks=[ToolAuditHook(log_file="audit.jsonl", fail_on_log_error=True)],
    )

Each JSONL record looks like:
    {"timestamp": "2026-05-03T22:45:00+00:00", "tool_name": "search", "status": "success",
     "arguments": {"query": "AI news"}, "duration_ms": 342.15, "result": "{...}"}
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agno.utils.log import logger


class ToolAuditHook:
    """A tool hook that logs every tool call for audit and observability.

    Records tool name, arguments, result, duration, timestamp, and errors
    in structured JSON format. Supports file output (JSONL), callback functions,
    or both.

    Args:
        log_file: Path to a JSONL file for writing audit records. Each line is a JSON object.
        callback: A callable that receives the audit record dict after each tool call.
        log_arguments: Whether to include tool arguments in the audit record. Default True.
        log_results: Whether to include tool results in the audit record. Default True.
        max_result_length: Maximum character length for result values in the log. Default 1000.
            Set to 0 to disable truncation.
        include_tools: Only log calls to these tool names. If None, log all tools.
        exclude_tools: Skip logging for these tool names.
        fail_on_log_error: If True, raise an exception when audit logging fails instead of
            silently continuing. Use this for compliance-critical scenarios where every tool
            call must be audited. Default False.
    """

    def __init__(
        self,
        log_file: Optional[str] = None,
        callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
        log_arguments: bool = True,
        log_results: bool = True,
        max_result_length: int = 1000,
        include_tools: Optional[List[str]] = None,
        exclude_tools: Optional[List[str]] = None,
        fail_on_log_error: bool = False,
    ):
        if not log_file and not callback:
            raise ValueError("ToolAuditHook requires at least one of log_file or callback.")

        self.log_file = log_file
        self.callback = callback
        self.log_arguments = log_arguments
        self.log_results = log_results
        self.max_result_length = max_result_length
        self.include_tools = set(include_tools) if include_tools else None
        self.exclude_tools = set(exclude_tools) if exclude_tools else None
        self.fail_on_log_error = fail_on_log_error

        # Ensure log directory exists
        if self.log_file:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)

    def _should_log(self, tool_name: str) -> bool:
        """Check if this tool call should be logged based on include/exclude filters."""
        if self.include_tools and tool_name not in self.include_tools:
            return False
        if self.exclude_tools and tool_name in self.exclude_tools:
            return False
        return True

    def _truncate_result(self, result: Any) -> Any:
        """Truncate result string if it exceeds max_result_length."""
        if self.max_result_length <= 0:
            return result
        result_str = str(result)
        if len(result_str) > self.max_result_length:
            return result_str[: self.max_result_length] + f"... [truncated, {len(result_str)} chars total]"
        return result_str

    def _build_record(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any = None,
        error: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build a structured audit record."""
        record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name,
            "status": "error" if error else "success",
        }
        if self.log_arguments:
            record["arguments"] = arguments
        if duration_ms is not None:
            record["duration_ms"] = round(duration_ms, 2)
        if error:
            record["error"] = str(error)
        elif self.log_results and result is not None:
            record["result"] = self._truncate_result(result)
        return record

    def _write_record(self, record: Dict[str, Any]) -> None:
        """Write the audit record to file and/or callback."""
        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    f.write(json.dumps(record, default=str) + "\n")
            except Exception as e:
                if self.fail_on_log_error:
                    raise RuntimeError(f"ToolAuditHook: failed to write audit log to {self.log_file}: {e}") from e
                logger.warning(f"ToolAuditHook: failed to write to {self.log_file}: {e}")

        if self.callback:
            try:
                self.callback(record)
            except Exception as e:
                if self.fail_on_log_error:
                    raise RuntimeError(f"ToolAuditHook: audit callback failed: {e}") from e
                logger.warning(f"ToolAuditHook: callback error: {e}")

    def __call__(self, function_name: str, function_call: Callable, arguments: Dict[str, Any]) -> Any:
        """Sync hook: wraps a tool call with audit logging."""
        if not self._should_log(function_name):
            return function_call(**arguments)

        start = time.monotonic()
        error = None
        result = None
        try:
            result = function_call(**arguments)
            return result
        except Exception as e:
            error = str(e)
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            record = self._build_record(
                tool_name=function_name,
                arguments=arguments,
                result=result,
                error=error,
                duration_ms=duration_ms,
            )
            self._write_record(record)
