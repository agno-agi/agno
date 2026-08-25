"""Errors raised by the CodeMode toolkit."""

from __future__ import annotations


class CodeModeError(Exception):
    """Base class for all CodeMode errors."""


class KernelBusyError(CodeModeError):
    """Raised when the kernel is still executing a previous cell.

    Surfaced to the model as the tool error, so the message must tell it what
    to do next: wait and retry, or restart the environment.
    """

    def __init__(
        self,
        message: str = (
            "The code environment is still busy with the previous cell. "
            "Wait a moment and retry, or call restart to discard all state and start fresh."
        ),
    ) -> None:
        super().__init__(message)


class ResultTooLarge(CodeModeError):
    """Raised when a bridged tool call returns a payload over ``max_result_bytes``.

    ``tool_name`` is the bridged tool that produced the payload; ``size_bytes``
    is the payload size; ``limit`` is ``max_result_bytes``.
    """

    def __init__(self, message: str, *, tool_name: str, size_bytes: int, limit: int) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.size_bytes = size_bytes
        self.limit = limit


class KernelDiedError(CodeModeError):
    """Raised when the kernel process dies while a cell is in flight."""
