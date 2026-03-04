import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agno.os.utils import to_utc_datetime


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

        # Handle nested memory content (relevant for some memories migrated from v1)
        if isinstance(memory_dict["memory"], dict):
            if memory_dict["memory"].get("memory") is not None:
                memory = str(memory_dict["memory"]["memory"])
            else:
                try:
                    memory = json.dumps(memory_dict["memory"])
                except json.JSONDecodeError:
                    memory = str(memory_dict["memory"])
        else:
            memory = memory_dict["memory"]

        return cls(
            memory_id=memory_dict["memory_id"],
            user_id=str(memory_dict["user_id"]),
            agent_id=memory_dict.get("agent_id"),
            team_id=memory_dict.get("team_id"),
            memory=memory,
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
            last_memory_updated_at=to_utc_datetime(updated_at),
        )


class OptimizeMemoriesRequest(BaseModel):
    """Schema for memory optimization request"""

    user_id: str = Field(..., description="User ID to optimize memories for")
    model: Optional[str] = Field(
        default=None,
        description="Model to use for optimization in format 'provider:model_id' (e.g., 'openai:gpt-4o-mini', 'anthropic:claude-3-5-sonnet-20241022', 'google:gemini-2.0-flash-exp'). If not specified, uses MemoryManager's default model (gpt-4o).",
    )
    apply: bool = Field(
        default=True,
        description="If True, apply optimization changes to database. If False, return preview only without saving.",
    )


class OptimizeMemoriesResponse(BaseModel):
    """Schema for memory optimization response"""

    memories: List[UserMemorySchema] = Field(..., description="List of optimized memory objects")
    memories_before: int = Field(..., description="Number of memories before optimization", ge=0)
    memories_after: int = Field(..., description="Number of memories after optimization", ge=0)
    tokens_before: int = Field(..., description="Token count before optimization", ge=0)
    tokens_after: int = Field(..., description="Token count after optimization", ge=0)
    tokens_saved: int = Field(..., description="Number of tokens saved through optimization", ge=0)
    reduction_percentage: float = Field(..., description="Percentage of token reduction achieved", ge=0.0, le=100.0)
