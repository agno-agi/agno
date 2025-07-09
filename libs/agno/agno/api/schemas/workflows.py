from typing import Any, Dict, Optional

from pydantic import BaseModel


class WorkflowRunCreate(BaseModel):
    """Data sent to API to create a Workflow Run"""

    session_id: str
    run_id: Optional[str] = None
    run_data: Optional[Dict[str, Any]] = None
    workflow_data: Optional[Dict[str, Any]] = None
