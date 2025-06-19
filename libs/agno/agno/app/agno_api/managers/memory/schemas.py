from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from agno.db.schemas.memory import MemoryRow
from agno.memory.memory import UserMemory


class UserMemorySchema(BaseModel):
    memory_id: str
    memory: str
    topics: Optional[List[str]]
    last_updated: Optional[datetime]

    @classmethod
    def from_memory_row(cls, memory_row: MemoryRow) -> "UserMemorySchema":
        return cls(
            memory_id=memory_row.id,  # type: ignore
            memory=memory_row.memory["memory"],
            topics=memory_row.memory.get("topics", []),
            last_updated=memory_row.last_updated,
        )

    @classmethod
    def from_user_memory(cls, memory: UserMemory) -> "UserMemorySchema":
        return cls(
            memory_id=memory.memory_id,  # type: ignore
            memory=memory.memory,
            topics=memory.topics,
            last_updated=memory.last_updated,
        )


class UserMemoryCreateSchema(BaseModel):
    """Define the payload expected for creating a new user memory"""

    memory: str
    user_id: str
    topics: Optional[List[str]] = None
