from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from agno.run.response import RunResponse
from agno.utils.log import logger


class WorkflowRun(BaseModel):
    input: Optional[Dict[str, Any]] = None
    response: Optional[RunResponse] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class WorkflowMemory(BaseModel):
    runs: List[WorkflowRun] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)

    def add_run(self, workflow_run: WorkflowRun) -> None:
        """Adds a WorkflowRun to the runs list."""
        self.runs.append(workflow_run)
        logger.debug("Added WorkflowRun to WorkflowMemory")

    def clear(self) -> None:
        """Clear the WorkflowMemory"""

        self.runs = []

    def deep_copy(self, *, update: Optional[Dict[str, Any]] = None) -> "WorkflowMemory":
        new_memory = self.model_copy(deep=True, update=update)
        # clear the new memory to remove any references to the old memory
        new_memory.clear()
        return new_memory
