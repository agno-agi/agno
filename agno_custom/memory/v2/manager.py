"""V1 memory manager compatibility stub.

V1 had: agno.memory.v2.manager.MemoryManager
V2 has: agno.memory.manager.MemoryManager

This module re-exports the V2 version for V1 compatibility.
"""

from agno.memory.manager import MemoryManager

__all__ = ["MemoryManager"]
