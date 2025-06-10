from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel

from agno.utils.log import log_error


class RunEvent(str, Enum):
    """Events that can be sent by the run() functions"""

    workflow_started = "WorkflowStarted"
    workflow_completed = "WorkflowCompleted"


@dataclass
class BaseWorkflowRunResponseEvent:
    run_id: str
    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""

    # For backwards compatibility
    content: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = {k: v for k, v in asdict(self).items() if v is not None}

        if hasattr(self, "content") and self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        return _dict

    def to_json(self) -> str:
        import json

        try:
            _dict = self.to_dict()
        except Exception:
            log_error("Failed to convert response to json", exc_info=True)
            raise

        return json.dumps(_dict, indent=2)


@dataclass
class WorkflowRunResponseStartedEvent(BaseWorkflowRunResponseEvent):
    event: str = RunEvent.workflow_started.value


@dataclass
class WorkflowCompletedEvent(BaseWorkflowRunResponseEvent):
    event: str = RunEvent.workflow_completed.value
    content: Optional[Any] = None
    content_type: str = "str"


WorkflowRunResponseEvent = Union[WorkflowRunResponseStartedEvent, WorkflowCompletedEvent]
