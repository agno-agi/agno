from typing import List, Optional

from a2a.types import Task
from pydantic import BaseModel


class CancelTaskEndpointResponse(BaseModel):
    """Response schema for the Cancel Task endpoints."""

    jsonrpc: str = "2.0"
    id: str
    result: Task


class GetTaskEndpointResponse(BaseModel):
    """Response schema for the Task endpoints."""

    jsonrpc: str = "2.0"
    id: Optional[str] = None
    result: Task


class ListTasksEndpointResponse(BaseModel):
    """Response schema for the List Tasks endpoints."""

    jsonrpc: str = "2.0"
    id: Optional[str] = None
    result: List[Task]
