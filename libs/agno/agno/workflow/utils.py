from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class WorkflowAction(Enum):
    respond_directly = "respond_directly"
    continue_workflow = "continue_workflow"
    ask_for_more_information = "ask_for_more_information"


class WorkflowResponse(BaseModel):
    action: WorkflowAction
    content: str
    workflow_input: Optional[str] = Field(
        default=None,
        description="Required when action is continue_workflow",
    )
