"""Advanced session search request and discoverable filter fields."""

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

from agno.db.base import SessionType
from agno.db.session_filters import SESSION_FILTER_FIELDS
from agno.os.routers.traces.schemas import FilterFieldSchema, FilterSchemaResponse

SESSION_FILTER_SCHEMA = FilterSchemaResponse(
    fields=[FilterFieldSchema(key=key, **field) for key, field in SESSION_FILTER_FIELDS.items()],
    logical_operators=["AND", "OR", "NOT"],
)


class SessionSearchRequest(BaseModel):
    filter: Optional[Dict[str, Any]] = None
    session_type: Optional[SessionType] = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    sort_by: Literal["created_at", "updated_at"] = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"
