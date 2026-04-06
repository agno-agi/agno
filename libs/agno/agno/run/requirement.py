from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.models.response import ToolExecution, UserFeedbackQuestion, UserInputField


@dataclass
class RunRequirement:
    """Requirement to complete a paused run (used in HITL flows)"""

    tool_execution: Optional[ToolExecution] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # User confirmation
    confirmation: Optional[bool] = None
    confirmation_note: Optional[str] = None

    # User input
    user_input_schema: Optional[List[UserInputField]] = None

    # User feedback (structured questions with options)
    user_feedback_schema: Optional[List[UserFeedbackQuestion]] = None

    # External execution
    external_execution_result: Optional[str] = None

    # Member context (set when requirement originates from a team member)
    member_agent_id: Optional[str] = None
    member_agent_name: Optional[str] = None
    member_run_id: Optional[str] = None

    def __init__(
        self,
        tool_execution: ToolExecution,
        id: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ):
        self.id = id or str(uuid4())
        self.tool_execution = tool_execution
        self.user_input_schema = tool_execution.user_input_schema if tool_execution else None
        self.user_feedback_schema = tool_execution.user_feedback_schema if tool_execution else None
        self.created_at = created_at or datetime.now(timezone.utc)
        self.confirmation = None
        self.confirmation_note = None
        self.external_execution_result = None
        self.member_agent_id = None
        self.member_agent_name = None
        self.member_run_id = None
        # Internal: holds a reference to the member's paused RunOutput so
        # continue_run can pass it directly without a session lookup.
        self._member_run_response: Any = None

    @property
    def needs_confirmation(self) -> bool:
        if self.confirmation is not None:
            return False
        if not self.tool_execution:
            return False
        if self.tool_execution.confirmed is not None:
            return False

        return self.tool_execution.requires_confirmation or False

    @property
    def needs_user_input(self) -> bool:
        if not self.tool_execution:
            return False
        if self.tool_execution.answered is True:
            return False
        if self.tool_execution.requires_user_input:
            return True
        if self.user_input_schema and not all(field.value is not None for field in self.user_input_schema):
            return True

        return False

    @property
    def needs_user_feedback(self) -> bool:
        if not self.tool_execution:
            return False
        if self.tool_execution.answered is True:
            return False
        if self.user_feedback_schema and not all(q.selected_options is not None for q in self.user_feedback_schema):
            return True
        return False

    @property
    def needs_external_execution(self) -> bool:
        if not self.tool_execution:
            return False
        if self.external_execution_result is not None:
            return False

        return self.tool_execution.external_execution_required or False

    def confirm(self):
        if not self.needs_confirmation:
            raise ValueError("This requirement does not require confirmation")
        self.confirmation = True
        if self.tool_execution:
            self.tool_execution.confirmed = True

    def reject(self, note: Optional[str] = None):
        if not self.needs_confirmation:
            raise ValueError("This requirement does not require confirmation")
        self.confirmation = False
        self.confirmation_note = note
        if self.tool_execution:
            self.tool_execution.confirmed = False
            self.tool_execution.confirmation_note = note

    def provide_user_input(self, values: Dict[str, Any]) -> None:
        """Provide user input values for a user-input requirement.

        Args:
            values: A dictionary mapping field names to their values.
        """
        if not self.needs_user_input:
            raise ValueError("This requirement does not require user input")
        if self.user_input_schema:
            for input_field in self.user_input_schema:
                if input_field.name in values:
                    input_field.value = values[input_field.name]
            # Also update tool_execution's user_input_schema so handle_user_input_update can copy to tool_args
            if self.tool_execution and self.tool_execution.user_input_schema:
                for tool_input_field in self.tool_execution.user_input_schema:
                    if tool_input_field.name in values:
                        tool_input_field.value = values[tool_input_field.name]
            # Only mark as answered when all fields have values
            if all(f.value is not None for f in self.user_input_schema) and self.tool_execution:
                self.tool_execution.answered = True

    def provide_user_feedback(self, selections: Dict[str, List[str]]) -> None:
        """Provide user feedback selections for a user-feedback requirement.

        Args:
            selections: A dictionary mapping question text to lists of selected option labels.
        """
        if not self.needs_user_feedback:
            raise ValueError("This requirement does not require user feedback")
        if self.user_feedback_schema:
            for question in self.user_feedback_schema:
                if question.question in selections:
                    question.selected_options = selections[question.question]
                    if question.options:
                        for opt in question.options:
                            opt.selected = opt.label in question.selected_options
            # Also update tool_execution's user_feedback_schema
            if self.tool_execution and self.tool_execution.user_feedback_schema:
                for tool_question in self.tool_execution.user_feedback_schema:
                    if tool_question.question in selections:
                        tool_question.selected_options = selections[tool_question.question]
                        if tool_question.options:
                            for opt in tool_question.options:
                                opt.selected = opt.label in tool_question.selected_options
            # Mark as answered when all questions have selections
            if all(q.selected_options is not None for q in self.user_feedback_schema) and self.tool_execution:
                self.tool_execution.answered = True

    def set_external_execution_result(self, result: str):
        if not self.needs_external_execution:
            raise ValueError("This requirement does not require external execution")
        self.external_execution_result = result
        if self.tool_execution:
            self.tool_execution.result = result

    def is_resolved(self) -> bool:
        """Return True if the requirement has been resolved"""
        return (
            not self.needs_confirmation
            and not self.needs_user_input
            and not self.needs_user_feedback
            and not self.needs_external_execution
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary for storage."""
        _dict: Dict[str, Any] = {
            "id": self.id,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "confirmation": self.confirmation,
            "confirmation_note": self.confirmation_note,
            "external_execution_result": self.external_execution_result,
            "member_agent_id": self.member_agent_id,
            "member_agent_name": self.member_agent_name,
            "member_run_id": self.member_run_id,
        }

        if self.tool_execution is not None:
            _dict["tool_execution"] = (
                self.tool_execution.to_dict() if isinstance(self.tool_execution, ToolExecution) else self.tool_execution
            )

        if self.user_input_schema is not None:
            _dict["user_input_schema"] = [f.to_dict() if hasattr(f, "to_dict") else f for f in self.user_input_schema]

        if self.user_feedback_schema is not None:
            _dict["user_feedback_schema"] = [
                q.to_dict() if hasattr(q, "to_dict") else q for q in self.user_feedback_schema
            ]

        return {k: v for k, v in _dict.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunRequirement":
        """Reconstruct from stored dictionary."""
        if data is None:
            raise ValueError("RunRequirement.from_dict() requires a non-None dict")

        # Handle tool_execution
        tool_data = data.get("tool_execution")
        tool_execution: Optional[ToolExecution] = None
        if isinstance(tool_data, ToolExecution):
            tool_execution = tool_data
        elif isinstance(tool_data, dict):
            tool_execution = ToolExecution.from_dict(tool_data)

        # Handle created_at (ISO string or datetime)
        created_at_raw = data.get("created_at")
        created_at: Optional[datetime] = None
        if isinstance(created_at_raw, datetime):
            created_at = created_at_raw
        elif isinstance(created_at_raw, str):
            try:
                created_at = datetime.fromisoformat(created_at_raw)
            except ValueError:
                created_at = None

        # Build requirement - tool_execution is required by __init__
        # For legacy data without tool_execution, create a minimal placeholder
        if tool_execution is None:
            tool_execution = ToolExecution(tool_name="unknown", tool_args={})

        requirement = cls(
            tool_execution=tool_execution,
            id=data.get("id"),
            created_at=created_at,
        )

        # Set optional fields
        requirement.confirmation = data.get("confirmation")
        requirement.confirmation_note = data.get("confirmation_note")
        requirement.external_execution_result = data.get("external_execution_result")
        requirement.member_agent_id = data.get("member_agent_id")
        requirement.member_agent_name = data.get("member_agent_name")
        requirement.member_run_id = data.get("member_run_id")

        # Handle user_input_schema
        schema_raw = data.get("user_input_schema")
        if schema_raw is not None:
            rebuilt_schema: List[UserInputField] = []
            for item in schema_raw:
                if isinstance(item, UserInputField):
                    rebuilt_schema.append(item)
                elif isinstance(item, dict):
                    rebuilt_schema.append(UserInputField.from_dict(item))
            requirement.user_input_schema = rebuilt_schema if rebuilt_schema else None

        # Handle user_feedback_schema
        feedback_raw = data.get("user_feedback_schema")
        if feedback_raw is not None:
            rebuilt_feedback: List[UserFeedbackQuestion] = []
            for item in feedback_raw:
                if isinstance(item, UserFeedbackQuestion):
                    rebuilt_feedback.append(item)
                elif isinstance(item, dict):
                    rebuilt_feedback.append(UserFeedbackQuestion.from_dict(item))
            requirement.user_feedback_schema = rebuilt_feedback if rebuilt_feedback else None

        return requirement
