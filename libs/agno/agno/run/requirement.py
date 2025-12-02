from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import uuid4

from agno.models.response import ToolExecution, UserInputField

if TYPE_CHECKING:
    pass


@dataclass
class RunRequirement:
    """Requirement to complete a paused run (used in HITL flows)"""

    tool_execution: Optional[ToolExecution] = None
    created_at: datetime = datetime.now(timezone.utc)

    # User confirmation
    confirmation: Optional[bool] = None
    confirmation_note: Optional[str] = None

    # User input
    user_input_schema: Optional[List[UserInputField]] = None
    user_input: Optional[List[Any]] = None

    # External execution
    external_execution_result: Optional[str] = None

    def __init__(self, tool_execution: ToolExecution):
        self.id = str(uuid4())
        self.tool_execution = tool_execution
        self.user_input_schema = tool_execution.user_input_schema

    @property
    def needs_confirmation(self) -> bool:
        if self.confirmation is True:
            return False
        if not self.tool_execution:
            return False
        if self.tool_execution.confirmed is True:
            return True

        return self.tool_execution.requires_confirmation or False

    @property
    def needs_user_input(self) -> bool:
        if self.user_input is not None:
            return True
        if not self.tool_execution:
            return False
        if self.tool_execution.answered is True:
            return True

        return self.tool_execution.requires_user_input or False

    @property
    def needs_external_execution(self) -> bool:
        if self.external_execution_result is not None:
            return True
        if not self.tool_execution:
            return False

        return self.tool_execution.external_execution_required or False

    def confirm(self):
        if not self.needs_confirmation:
            raise ValueError("This requirement does not require confirmation")
        self.confirmation = True
        if self.tool_execution:
            self.tool_execution.confirmed = True

    def reject(self):
        if not self.needs_confirmation:
            raise ValueError("This requirement does not require confirmation")
        self.confirmation = False
        if self.tool_execution:
            self.tool_execution.confirmed = False

    def set_external_execution_result(self, result: str):
        if not self.needs_external_execution:
            raise ValueError("This requirement does not require external execution")
        self.external_execution_result = result
        if self.tool_execution:
            self.tool_execution.result = result

    def update_tools(self, tools: List[ToolExecution]):
        if not self.tool_execution:
            return
        if self.confirmation is True:
            self.tool_execution.confirmed = True
        elif self.confirmation is False:
            self.tool_execution.confirmed = False
        else:
            raise ValueError("This requirement does not require confirmation or user input")

    def is_resolved(self) -> bool:
        """Return True if the requirement has been resolved"""
        return bool(
            self.confirmation is not None or self.user_input is not None or self.external_execution_result is not None
        )
