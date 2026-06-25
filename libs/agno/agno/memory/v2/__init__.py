"""V1 memory API compatibility stubs for V1→V2 migration.

V1 had structure: agno.memory.v2.db.postgres, agno.memory.v2.schema, etc.
V2 has simplified structure: agno.memory.*, agno.db.*

This module provides V1-compatible paths and classes.
"""

from agno.memory.v2 import db

__all__ = ["db"]
