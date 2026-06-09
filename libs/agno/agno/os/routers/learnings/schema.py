from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class LearningResponse(BaseModel):
    """A single learning record as returned by the API."""

    model_config = ConfigDict(extra="ignore")

    learning_id: str = Field(..., description="Unique identifier for the learning record")
    learning_type: str = Field(..., description="Type of learning (e.g. 'user_profile', 'entity_memory')")
    namespace: Optional[str] = Field(None, description="Namespace for scoping ('user', 'global', or custom)")
    user_id: Optional[str] = Field(None, description="Associated user ID")
    agent_id: Optional[str] = Field(None, description="Associated agent ID")
    team_id: Optional[str] = Field(None, description="Associated team ID")
    session_id: Optional[str] = Field(None, description="Associated session ID")
    entity_id: Optional[str] = Field(None, description="Associated entity ID (for entity-specific learnings)")
    entity_type: Optional[str] = Field(None, description="Entity type (e.g. 'person', 'company')")
    content: Optional[Dict[str, Any]] = Field(None, description="The learning content payload")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    created_at: Optional[int] = Field(None, description="Creation timestamp (Unix epoch seconds)")
    updated_at: Optional[int] = Field(None, description="Last update timestamp (Unix epoch seconds)")


class LearningCreate(BaseModel):
    """Request body for creating a learning record."""

    learning_type: str = Field(..., description="Type of learning (e.g. 'user_profile', 'entity_memory')")
    content: Dict[str, Any] = Field(..., description="The learning content payload")
    namespace: Optional[str] = Field(None, description="Namespace for scoping ('user', 'global', or custom)")
    user_id: Optional[str] = Field(
        None,
        description=(
            "Associated user ID. When the request is authenticated, must match the JWT "
            "subject or be omitted/null (which creates a global / non-user-scoped record)."
        ),
    )
    agent_id: Optional[str] = Field(None, description="Associated agent ID")
    team_id: Optional[str] = Field(None, description="Associated team ID")
    session_id: Optional[str] = Field(None, description="Associated session ID")
    entity_id: Optional[str] = Field(None, description="Associated entity ID")
    entity_type: Optional[str] = Field(None, description="Entity type")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")


class LearningUpdate(BaseModel):
    """Request body for updating a learning record. Identity fields are immutable."""

    content: Optional[Dict[str, Any]] = Field(None, description="Replacement content payload")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Replacement metadata")


class LearningUserStats(BaseModel):
    """A user that owns learning records, with their most recent activity.

    Used as a lightweight index for the per-user view: list users here, then drill into a
    single user's records via ``GET /learnings?user_id=...``. No per-user count is returned
    -- the user-scoped stores (``user_profile``, ``user_memory``) keep a single record per
    user, so a record count would always be 1; the actual memory count lives in that
    record's ``content``.
    """

    user_id: str = Field(..., description="The user ID")
    last_learning_updated_at: Optional[int] = Field(
        None, description="Most recent learning update for this user (Unix epoch seconds)"
    )
