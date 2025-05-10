from typing import Any, Dict, Optional

from pydantic import BaseModel


class WorkflowCreate(BaseModel):
    """Data sent to API to create aWorkflow"""

    workflow_id: str
    app_id: Optional[str] = None
    name: Optional[str] = None
    config: Dict[str, Any]
