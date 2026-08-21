from agno.compression._context import (
    SUMMARY_PREFIX,
    CompactionResult,
    CompactionState,
    create_summary_message,
)
from agno.compression.manager import CompactionManager

# Backward compatibility alias (deprecated, use CompactionManager)
CompressionManager = CompactionManager

__all__ = [
    "CompactionManager",
    "CompressionManager",  # Deprecated alias
    "CompactionState",
    "CompactionResult",
    "SUMMARY_PREFIX",
    "create_summary_message",
]
