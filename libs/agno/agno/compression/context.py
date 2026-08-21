"""Backward compatibility shim - imports from _context.py."""

from agno.compression._context import (
    DEFAULT_COMPACTION_PROMPT,
    SUMMARY_PREFIX,
    CompactionResult,
    CompactionState,
    ContextCompactionManager,
    create_summary_message,
)

__all__ = [
    "ContextCompactionManager",
    "CompactionState",
    "CompactionResult",
    "SUMMARY_PREFIX",
    "DEFAULT_COMPACTION_PROMPT",
    "create_summary_message",
]
