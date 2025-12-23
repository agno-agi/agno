from typing import List

from a2a.types import Task
from pydantic import BaseModel


class GetTaskEndpointResponse(BaseModel):
    """Response schema for the Task endpoints."""

    jsonrpc: str = "2.0"
    id: str
    result: Task


class ListTasksEndpointResponse(BaseModel):
    """Response schema for the List Tasks endpoints."""

    jsonrpc: str = "2.0"
    id: str
    result: List[Task]
