"""Decorators for workflow step configuration."""

from functools import wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar

F = TypeVar("F", bound=Callable)


def hitl(
    name: Optional[str] = None,
    requires_confirmation: bool = False,
    confirmation_message: Optional[str] = None,
    requires_user_input: bool = False,
    user_input_message: Optional[str] = None,
    user_input_schema: Optional[List[Dict[str, Any]]] = None,
) -> Callable[[F], F]:
    """Decorator to mark a step function with Human-In-The-Loop (HITL) configuration.

    This decorator adds HITL metadata to a function that will be used as a workflow step.
    When the function is passed to a Step or directly to a Workflow, the HITL configuration
    will be automatically detected and applied.

    Args:
        name: Optional name for the step. If not provided, the function name will be used.
        requires_confirmation: Whether the step requires user confirmation before execution.
            Defaults to False.
        confirmation_message: Message to display to the user when requesting confirmation.
        requires_user_input: Whether the step requires user input before execution.
            Defaults to False.
        user_input_message: Message to display to the user when requesting input.
        user_input_schema: Schema for user input fields. Each field is a dict with:
            - name: Field name (required)
            - field_type: "str", "int", "float", "bool" (default: "str")
            - description: Field description (optional)
            - required: Whether field is required (default: True)

    Returns:
        A decorator that adds HITL metadata to the function.

    Example:
        ```python
        from agno.workflow.decorators import hitl
        from agno.workflow.types import StepInput, StepOutput

        # Confirmation-based HITL
        @hitl(
            name="Delete Records",
            requires_confirmation=True,
            confirmation_message="About to delete records. Confirm?"
        )
        def delete_records(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Records deleted")

        # User input-based HITL
        @hitl(
            name="Process with Parameters",
            requires_user_input=True,
            user_input_message="Please provide processing parameters:",
            user_input_schema=[
                {"name": "threshold", "field_type": "float", "description": "Processing threshold"},
                {"name": "mode", "field_type": "str", "description": "Processing mode (fast/accurate)"},
            ]
        )
        def process_with_params(step_input: StepInput) -> StepOutput:
            # User input is available in step_input.additional_data["user_input"]
            user_input = step_input.additional_data.get("user_input", {})
            threshold = user_input.get("threshold", 0.5)
            mode = user_input.get("mode", "fast")
            return StepOutput(content=f"Processed with threshold={threshold}, mode={mode}")
        ```
    """

    def decorator(func: F) -> F:
        # Store HITL metadata on the function
        func._hitl_name = name  # type: ignore[attr-defined]
        func._hitl_requires_confirmation = requires_confirmation  # type: ignore[attr-defined]
        func._hitl_confirmation_message = confirmation_message  # type: ignore[attr-defined]
        func._hitl_requires_user_input = requires_user_input  # type: ignore[attr-defined]
        func._hitl_user_input_message = user_input_message  # type: ignore[attr-defined]
        func._hitl_user_input_schema = user_input_schema  # type: ignore[attr-defined]

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Copy HITL metadata to wrapper
        wrapper._hitl_name = name  # type: ignore[attr-defined]
        wrapper._hitl_requires_confirmation = requires_confirmation  # type: ignore[attr-defined]
        wrapper._hitl_confirmation_message = confirmation_message  # type: ignore[attr-defined]
        wrapper._hitl_requires_user_input = requires_user_input  # type: ignore[attr-defined]
        wrapper._hitl_user_input_message = user_input_message  # type: ignore[attr-defined]
        wrapper._hitl_user_input_schema = user_input_schema  # type: ignore[attr-defined]

        return wrapper  # type: ignore[return-value]

    return decorator


def get_hitl_metadata(func: Callable) -> dict:
    """Extract HITL metadata from a function if it has been decorated with @hitl.

    Args:
        func: The function to extract metadata from.

    Returns:
        A dictionary with HITL configuration, or empty dict if not decorated.
    """
    if not callable(func):
        return {}

    metadata = {}

    if hasattr(func, "_hitl_name"):
        metadata["name"] = func._hitl_name  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_requires_confirmation"):
        metadata["requires_confirmation"] = func._hitl_requires_confirmation  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_confirmation_message"):
        metadata["confirmation_message"] = func._hitl_confirmation_message  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_requires_user_input"):
        metadata["requires_user_input"] = func._hitl_requires_user_input  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_user_input_message"):
        metadata["user_input_message"] = func._hitl_user_input_message  # type: ignore[attr-defined]

    if hasattr(func, "_hitl_user_input_schema"):
        metadata["user_input_schema"] = func._hitl_user_input_schema  # type: ignore[attr-defined]

    return metadata


def has_hitl_metadata(func: Callable) -> bool:
    """Check if a function has HITL metadata from the @hitl decorator.

    Args:
        func: The function to check.

    Returns:
        True if the function has HITL metadata, False otherwise.
    """
    return hasattr(func, "_hitl_requires_confirmation") or hasattr(func, "_hitl_requires_user_input")
