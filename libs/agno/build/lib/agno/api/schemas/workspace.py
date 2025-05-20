from typing import Any, Dict, Optional

from pydantic import BaseModel


class WorkspaceCreate(BaseModel):
    ws_name: str
    git_url: Optional[str] = None
    visibility: Optional[str] = None
    ws_data: Optional[Dict[str, Any]] = None


class WorkspaceUpdate(BaseModel):
    id_workspace: str
    ws_name: Optional[str] = None
    git_url: Optional[str] = None
    visibility: Optional[str] = None
    ws_data: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class WorkspaceDelete(BaseModel):
    id_workspace: str
    ws_name: Optional[str] = None


class WorkspaceEvent(BaseModel):
    id_workspace: str
    event_type: str
    event_status: str
    event_data: Optional[Dict[str, Any]] = None


class WorkspaceSchema(BaseModel):
    """Workspace data returned by the API."""

    id_workspace: Optional[str] = None
    ws_name: Optional[str] = None
    is_active: Optional[bool] = None
    git_url: Optional[str] = None
    ws_data: Optional[Dict[str, Any]] = None


class WorkspaceIdentifier(BaseModel):
    ws_key: Optional[str] = None
    id_workspace: Optional[str] = None
