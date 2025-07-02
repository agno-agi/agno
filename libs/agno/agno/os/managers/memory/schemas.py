from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class DeleteMemoriesRequest(BaseModel):
    memory_ids: List[str]


class UserMemorySchema(BaseModel):
    memory_id: str
    memory: str
    topics: Optional[List[str]]

    agent_id: Optional[str]
    team_id: Optional[str]
    workflow_id: Optional[str]
    user_id: Optional[str]

    last_updated: Optional[datetime]

    @classmethod
    def from_dict(cls, memory_dict: Dict[str, Any]) -> "UserMemorySchema":
        return cls(
            memory_id=memory_dict["memory_id"],
            user_id=memory_dict["user_id"],
            agent_id=memory_dict["agent_id"],
            team_id=memory_dict["team_id"],
            workflow_id=memory_dict["workflow_id"],
            memory=memory_dict["memory"]["memory"],
            topics=memory_dict["topics"],
            last_updated=memory_dict["last_updated"],
        )


class UserMemoryCreateSchema(BaseModel):
    """Define the payload expected for creating a new user memory"""

    memory: str
    user_id: str
    topics: Optional[List[str]] = None


class UserStatsSchema(BaseModel):
    """Schema for user memory statistics"""

    user_id: str
    total_memories: int
    last_memory_updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, user_stats_dict: Dict[str, Any]) -> "UserStatsSchema":
        last_updated_at = user_stats_dict.get("last_memory_updated_at")

        return cls(
            user_id=user_stats_dict["user_id"],
            total_memories=user_stats_dict["total_memories"],
            last_memory_updated_at=datetime.fromtimestamp(last_updated_at, tz=timezone.utc)
            if last_updated_at
            else None,
        )
