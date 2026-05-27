"""V1 storage API compatibility stubs for V1→V2 migration.

V1 had: agno.storage.postgres, agno.storage.base, agno.storage.session
V2 has: Different storage structure

This module provides V1-compatible paths.
"""

from agno.storage.base import Storage
from agno.storage.postgres import PostgresStorage
from agno.storage import session

__all__ = ["Storage", "PostgresStorage", "session"]
