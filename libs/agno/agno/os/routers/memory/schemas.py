from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DeleteMemoriesRequest(BaseModel):
    memory_ids: List[str] = Field(..., description="List of memory IDs to delete", min_length=1)
    user_id: Optional[str] = Field(None, description="User ID to filter memories for deletion")


class UserMemorySchema(BaseModel):
    memory_id: str = Field(..., description="Unique identifier for the memory")
    memory: str = Field(..., description="Memory content text")
    topics: Optional[List[str]] = Field(None, description="Topics or tags associated with the memory")

    agent_id: Optional[str] = Field(None, description="Agent ID associated with this memory")
    team_id: Optional[str] = Field(None, description="Team ID associated with this memory")
    user_id: Optional[str] = Field(None, description="User ID who owns this memory")

    updated_at: Optional[datetime] = Field(None, description="Timestamp when memory was last updated")

    @classmethod
    def from_dict(cls, memory_dict: Dict[str, Any]) -> Optional["UserMemorySchema"]:
        if memory_dict["memory"] == "":
            return None

        return cls(
            memory_id=memory_dict["memory_id"],
            user_id=str(memory_dict["user_id"]),
            agent_id=memory_dict.get("agent_id"),
            team_id=memory_dict.get("team_id"),
            memory=memory_dict["memory"],
            topics=memory_dict.get("topics", []),
            updated_at=memory_dict["updated_at"],
        )


class UserMemoryCreateSchema(BaseModel):
    """Define the payload expected for creating a new user memory"""

    memory: str = Field(..., description="Memory content text", min_length=1, max_length=5000)
    user_id: Optional[str] = Field(None, description="User ID who owns this memory")
    topics: Optional[List[str]] = Field(None, description="Topics or tags to categorize the memory")


class UserStatsSchema(BaseModel):
    """Schema for user memory statistics"""

    user_id: str = Field(..., description="User ID")
    total_memories: int = Field(..., description="Total number of memories for this user", ge=0)
    last_memory_updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent memory update")

    @classmethod
    def from_dict(cls, user_stats_dict: Dict[str, Any]) -> "UserStatsSchema":
        updated_at = user_stats_dict.get("last_memory_updated_at")

        return cls(
            user_id=str(user_stats_dict["user_id"]),
            total_memories=user_stats_dict["total_memories"],
            last_memory_updated_at=datetime.fromtimestamp(updated_at, tz=timezone.utc) if updated_at else None,
        )
